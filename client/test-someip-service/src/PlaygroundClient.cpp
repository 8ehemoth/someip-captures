// PlaygroundClient.cpp (FINAL - heartbeat/ping ready)
// 핵심:
// - buildProxy<PlaygroundProxy>("local","1","graphql") connection 명시
// - --ping 모드: isAvailable()만 확인하고 종료 (부작용 없음)
// - --ping_timeout_ms로 무한 대기 방지
// - 일반 모드: 기존 door/seat set 동작 유지 (기존 실험용)
// - --help 지원

#include <CommonAPI/CommonAPI.hpp>

#include <v1/org/genivi/vehicle/playground/PlaygroundProxy.hpp>
#include <org/genivi/vehicle/playgroundtypes/PlaygroundTypes.hpp>

#include <iostream>
#include <string>
#include <vector>
#include <sstream>
#include <algorithm>
#include <thread>
#include <chrono>
#include <unistd.h>

using namespace std;
using namespace v1_0::org::genivi::vehicle::playground;

using DoorCommand     = ::org::genivi::vehicle::playgroundtypes::PlaygroundTypes::DoorCommand;
using CarDoorsCommand = ::org::genivi::vehicle::playgroundtypes::PlaygroundTypes::CarDoorsCommand;

static bool hasFlag(int argc, char** argv, const std::string& flag) {
    for (int i = 1; i < argc; i++) {
        if (std::string(argv[i]) == flag) return true;
    }
    return false;
}

static std::string getArgValue(int argc, char** argv, const std::string& key, const std::string& def = "") {
    for (int i = 1; i < argc; i++) {
        if (std::string(argv[i]) == key && i + 1 < argc) return std::string(argv[i + 1]);
    }
    return def;
}

static vector<int> parseIntList(const string& s) {
    vector<int> out;
    string token;
    stringstream ss(s);
    while (getline(ss, token, ',')) {
        if (token.empty()) continue;
        out.push_back(stoi(token));
    }
    return out;
}

static DoorCommand doorLiteral(const string& m) {
    string u = m;
    transform(u.begin(), u.end(), u.begin(), ::toupper);
    if (u == "OPEN")  return DoorCommand(DoorCommand::Literal::OPEN_DOOR);
    return DoorCommand(DoorCommand::Literal::CLOSE_DOOR);
}

static void printHelp(const char* prog) {
    std::cout
        << "Usage: " << prog << " [options]\n"
        << "\n"
        << "Heartbeat:\n"
        << "  --ping                     : Check proxy availability only (no side effects)\n"
        << "  --ping_timeout_ms <ms>     : Timeout for availability (default 1000)\n"
        << "\n"
        << "Normal actions (side effects - for experiments):\n"
        << "  --door <OPEN|CLOSE>        : door command (default OPEN)\n"
        << "  --seat_status <csv 7 ints> : seat heating status (default 0,0,0,0,0,0,0)\n"
        << "  --seat_level <csv 7 ints>  : seat heating level (default 0,0,0,0,0,0,0)\n"
        << "  --count <n>                : repeat count (default 1)\n"
        << "  --delay <sec>              : sleep between iterations (default 0)\n"
        << "\n";
}

int main(int argc, char** argv) {
    if (hasFlag(argc, argv, "--help") || hasFlag(argc, argv, "-h")) {
        printHelp(argv[0]);
        return 0;
    }

    // modes
    bool ping_only = hasFlag(argc, argv, "--ping");
    int ping_timeout_ms = stoi(getArgValue(argc, argv, "--ping_timeout_ms", "1000"));

    // normal args
    string door_mode = getArgValue(argc, argv, "--door", "OPEN");
    string seat_status_s = getArgValue(argc, argv, "--seat_status", "0,0,0,0,0,0,0");
    string seat_level_s  = getArgValue(argc, argv, "--seat_level",  "0,0,0,0,0,0,0");
    int count = stoi(getArgValue(argc, argv, "--count", "1"));
    int delay = stoi(getArgValue(argc, argv, "--delay", "0"));

    // connection (must match VSOMEIP_APPLICATION_NAME and vsomeip-client-sd.json applications.name)
    const std::string connection = "graphql";

    std::shared_ptr<CommonAPI::Runtime> runtime = CommonAPI::Runtime::get();

    // debug
    std::cerr << "[DBG] buildProxy(domain=local, instance=1, connection=" << connection << ")\n";

    std::shared_ptr<PlaygroundProxy<>> proxy =
        runtime->buildProxy<PlaygroundProxy>("local", "1", connection);

    if (!proxy) {
        std::cerr << "[ERROR] buildProxy() returned null.\n"
                  << "        domain=local\n"
                  << "        instance=1\n"
                  << "        connection=" << connection << "\n"
                  << "        (Check: VSOMEIP_APPLICATION_NAME and vsomeip-client-sd.json applications.name)\n";
        return 11;
    }

    // availability wait with timeout
    auto start = std::chrono::steady_clock::now();
    auto deadline = start + std::chrono::milliseconds(ping_timeout_ms);

    while (!proxy->isAvailable()) {
        if (ping_timeout_ms > 0 && std::chrono::steady_clock::now() > deadline) {
            std::cerr << "[PING] not available within timeout_ms=" << ping_timeout_ms << "\n";
            return 124; // timeout-like exit code
        }
        // 10ms sleep
        usleep(10 * 1000);
    }

    if (ping_only) {
        std::cout << "[PING] ok\n";
        return 0;
    }

    std::cout << "Available.\n";

    CommonAPI::CallStatus status;

    const int N = 7;
    vector<int> seat_status_i = parseIntList(seat_status_s);
    vector<int> seat_level_i  = parseIntList(seat_level_s);
    seat_status_i.resize(N, 0);
    seat_level_i.resize(N, 0);

    for (int iter = 0; iter < count; iter++) {
        DoorCommand fl = doorLiteral(door_mode);
        DoorCommand fr = doorLiteral(door_mode);
        DoorCommand rl(DoorCommand::Literal::NOTHING);
        DoorCommand rr(DoorCommand::Literal::NOTHING);
        CarDoorsCommand cmd(fl, fr, rl, rr);

        proxy->changeDoorsState(cmd, status);
        std::cout << "[#" << (iter + 1) << "] changeDoorsState(" << door_mode
                  << ") CallStatus=" << (int)status << std::endl;

        std::vector<bool> seatStatus(N, false);
        for (int i = 0; i < N; i++) seatStatus[i] = (seat_status_i[i] != 0);

        std::vector<bool> seatStatusResp;
        proxy->getSeatHeatingStatusAttribute().setValue(seatStatus, status, seatStatusResp);
        std::cout << "[#" << (iter + 1) << "] setSeatHeatingStatusAttribute(size=" << seatStatus.size()
                  << ") CallStatus=" << (int)status << std::endl;

        std::vector<uint8_t> seatLevel(N, 0);
        for (int i = 0; i < N; i++) {
            int v = seat_level_i[i];
            if (v < 0) v = 0;
            if (v > 255) v = 255;
            seatLevel[i] = (uint8_t)v;
        }

        std::vector<uint8_t> seatLevelResp;
        proxy->getSeatHeatingLevelAttribute().setValue(seatLevel, status, seatLevelResp);
        std::cout << "[#" << (iter + 1) << "] setSeatHeatingLevelAttribute(size=" << seatLevel.size()
                  << ") CallStatus=" << (int)status << std::endl;

        if (delay > 0) std::this_thread::sleep_for(std::chrono::seconds(delay));
    }

    return 0;
}
