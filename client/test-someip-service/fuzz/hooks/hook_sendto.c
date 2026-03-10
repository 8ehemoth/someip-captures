// fuzz/hooks/hook_sendto.c
// Purpose:
//  - LD_PRELOAD hook for sendmsg()
//  - Mutate ONLY connected AF_INET sockets whose peer port == FUZZ_ONLY_PORT (default: 31000)
//  - Avoid touching netlink/unix/internal sockets
//  - Protect SOME/IP header by skipping first FUZZ_SKIP bytes (default: 16)
// Usage example:
//  FUZZ_ENABLE=1 FUZZ_ONLY_PORT=31000 FUZZ_SKIP=16 FUZZ_NFLIPS=2 FUZZ_SEED=1 \
//  LD_PRELOAD=$PWD/fuzz/hooks/hook_sendto.so python3 run_client.py 2>hook.err | tee client.log

#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <time.h>

#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>

/* -------------------- helpers -------------------- */
static int env_int(const char *name, int defv) {
    const char *v = getenv(name);
    if (!v || !*v) return defv;
    return atoi(v);
}

static uint32_t env_u32(const char *name, uint32_t defv) {
    const char *v = getenv(name);
    if (!v || !*v) return defv;
    return (uint32_t)strtoul(v, NULL, 10);
}

static uint32_t xorshift32(uint32_t *state) {
    uint32_t x = *state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *state = x;
    return x;
}

/* -------------------- real function ptr -------------------- */
static ssize_t (*real_sendmsg)(int, const struct msghdr*, int) = NULL;

/* -------------------- hook: sendmsg -------------------- */
ssize_t sendmsg(int sockfd, const struct msghdr *msg, int flags)
{
    if (!real_sendmsg) {
        real_sendmsg = dlsym(RTLD_NEXT, "sendmsg");
        if (!real_sendmsg) {
            errno = ENOSYS;
            return -1;
        }
    }

    const int enable = env_int("FUZZ_ENABLE", 0);
    if (!enable || !msg || !msg->msg_iov || msg->msg_iovlen <= 0) {
        return real_sendmsg(sockfd, msg, flags);
    }

    /* Filter: only connected AF_INET sockets to FUZZ_ONLY_PORT */
    const int only_port = env_int("FUZZ_ONLY_PORT", 31000);

    struct sockaddr_storage peer;
    socklen_t peerlen = sizeof(peer);
    if (getpeername(sockfd, (struct sockaddr*)&peer, &peerlen) != 0) {
        // Not a connected INET socket (netlink/unix, etc.)
        return real_sendmsg(sockfd, msg, flags);
    }

    if (((struct sockaddr*)&peer)->sa_family != AF_INET) {
        return real_sendmsg(sockfd, msg, flags);
    }

    const int dport = ntohs(((struct sockaddr_in*)&peer)->sin_port);
    if (only_port > 0 && dport != only_port) {
        return real_sendmsg(sockfd, msg, flags);
    }

    /* Target buffer: mutate iov[0] only (safe copy) */
    const void *orig = msg->msg_iov[0].iov_base;
    const size_t len = msg->msg_iov[0].iov_len;

    if (!orig || len < 20) {
        return real_sendmsg(sockfd, msg, flags);
    }

    int skip = env_int("FUZZ_SKIP", 16);    // SOME/IP header ~16 bytes
    int nflips = env_int("FUZZ_NFLIPS", 1); // number of bit flips

    if (skip < 0) skip = 0;
    if ((size_t)skip >= len) {
        return real_sendmsg(sockfd, msg, flags);
    }
    if (nflips < 1) nflips = 1;
    if (nflips > 128) nflips = 128;

    uint32_t seed = env_u32("FUZZ_SEED", 0);
    if (seed == 0) {
        struct timespec ts;
        clock_gettime(CLOCK_REALTIME, &ts);
        seed = (uint32_t)(ts.tv_nsec ^ ts.tv_sec);
    }

    uint8_t *tmp = (uint8_t*)malloc(len);
    if (!tmp) {
        return real_sendmsg(sockfd, msg, flags);
    }
    memcpy(tmp, orig, len);

    char ipbuf[64] = {0};
    inet_ntop(AF_INET, &((struct sockaddr_in*)&peer)->sin_addr, ipbuf, sizeof(ipbuf));

    fprintf(stderr,
            "[HOOK] sendmsg sock=%d peer=%s:%d len=%zu skip=%d flips=%d seed=%u\n",
            sockfd, ipbuf, dport, len, skip, nflips, seed);

    for (int i = 0; i < nflips; i++) {
        uint32_t r = xorshift32(&seed);
        size_t pos = (size_t)skip + (r % (len - (size_t)skip));
        uint8_t before = tmp[pos];
        tmp[pos] ^= (uint8_t)(0x01u << (r % 8)); // flip 1 bit
        uint8_t after = tmp[pos];
        fprintf(stderr, "[HOOK] flip #%d pos=%zu %02x->%02x\n", i + 1, pos, before, after);
    }

    /* Build a new msghdr that points to our mutated iov[0] */
    struct msghdr msg2 = *msg;

    // Copy iov array
    struct iovec *iov_arr = (struct iovec*)malloc(sizeof(struct iovec) * (size_t)msg->msg_iovlen);
    if (!iov_arr) {
        free(tmp);
        return real_sendmsg(sockfd, msg, flags);
    }
    memcpy(iov_arr, msg->msg_iov, sizeof(struct iovec) * (size_t)msg->msg_iovlen);

    // Replace iov[0] with mutated buffer
    iov_arr[0].iov_base = tmp;
    iov_arr[0].iov_len  = len;

    msg2.msg_iov = iov_arr;

    ssize_t ret = real_sendmsg(sockfd, &msg2, flags);

    free(iov_arr);
    free(tmp);
    return ret;
}
