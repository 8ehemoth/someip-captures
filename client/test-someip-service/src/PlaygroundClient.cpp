// PlaygroundClient.cpp (FINAL - fixed connection match for CommonAPI-SomeIP)
// 핵심:
// - buildProxy<PlaygroundProxy>("local","1","graphql") 로 connection을 명시 (중요!)
// - connection(=vsomeip application name) == VSOMEIP_APPLICATION_NAME == vsomeip-client-sd.json applications.name
// - proxy 타입은 PlaygroundProxy<> (원본 패턴 유지)
// - argv: --door / --seat_status / --seat_level / --count / --delay 지원
// - Attribute::setValue 시그니처 (request, status, response) 맞춤

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

typedef ::org::genivi::vehicle::playgroundtypes::PlaygroundTypes::DoorsStatus DoorsStatus;

static string getArgValue(int argc, char** argv, const string& key, const string& def = "") {
    for (int i = 1; i < argc; i++) {
        if (string(argv[i]) == key && i + 1 < argc) return string(argv[i + 1]);
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

int main(int argc, char** argv) {
    string door_mode = getArgValue(argc, argv, "--door", "OPEN");
    string seat_status_s = getArgValue(argc, argv, "--seat_status", "0,0,0,0,0,0,0");
    string seat_level_s  = getArgValue(argc, argv, "--seat_level",  "0,0,0,0,0,0,0");
    int count = stoi(getArgValue(argc, argv, "--count", "1"));
    int delay = stoi(getArgValue(argc, argv, "--delay", "0"));

    // ★★★ 핵심 수정: connection을 명시해서 CommonAPI buildProxy 매칭을 강제 ★★★
    // connection == vsomeip application name
    const std::string connection = "graphql";

    std::shared_ptr<CommonAPI::Runtime> runtime = CommonAPI::Runtime::get();

    // 디버그: 실제 어떤 connection으로 프록시를 만들려는지 출력
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

    std::cout << "Checking availability..." << std::endl;
    while (!proxy->isAvailable())
        usleep(10);
    std::cout << "Available." << std::endl;

    CommonAPI::CallStatus status;

    using DoorCommand     = ::org::genivi::vehicle::playgroundtypes::PlaygroundTypes::DoorCommand;
    using CarDoorsCommand = ::org::genivi::vehicle::playgroundtypes::PlaygroundTypes::CarDoorsCommand;

    auto doorLiteral = [&](const string& m) -> DoorCommand {
        string u = m;
        transform(u.begin(), u.end(), u.begin(), ::toupper);
        if (u == "OPEN")  return DoorCommand(DoorCommand::Literal::OPEN_DOOR);
        return DoorCommand(DoorCommand::Literal::CLOSE_DOOR);
    };

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
