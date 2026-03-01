#  Copyright (C) 2021, Bayerische Motoren Werke Aktiengesellschaft (BMW AG),
#    Author: Alexander Domin (Alexander.Domin@bmw.de)
#  Copyright (C) 2021, ProFUSION Sistemas e Soluções LTDA,
#    Author: Leandro Ferlin (leandroferlin@profusion.mobi)
#    Author: Gabriel Fernandes Silva (g7fernandes@profusion.mobi)
#  SPDX-License-Identifier: MPL-2.0
#
#  This Source Code Form is subject to the terms of the
#  Mozilla Public License, v. 2.0. If a copy of the MPL was
#  not distributed with this file, You can obtain one at
#  http://mozilla.org/MPL/2.0/.
#

cmake_minimum_required(VERSION 3.13)
project(someip-server-playground)

# C++ 설정 (기존 -std=c++0x 대신)
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# pthread
set(THREADS_PREFER_PTHREAD_FLAG ON)
find_package(Threads REQUIRED)

find_package(CommonAPI 3.2 REQUIRED)
find_package(CommonAPI-SomeIP 3.2 REQUIRED)
find_package(vsomeip3 3.1.0 REQUIRED)

include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/commonapi-wrappers/playground/include
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${COMMONAPI_INCLUDE_DIRS}
    ${VSOMEIP3_INCLUDE_DIRS}
)

# -------------------------
# PlaygroundClient
# -------------------------
add_executable(PlaygroundClient
    src/PlaygroundClient.cpp
)

# "등록만 하고 직접 심볼 호출이 약한" 라이브러리가 --as-needed에 의해 빠지는 걸 방지
# (LD_PRELOAD로 해결됐던 케이스를 CMake 링크로 영구화)
target_link_options(PlaygroundClient PRIVATE "-Wl,--no-as-needed")

target_link_libraries(PlaygroundClient
    Threads::Threads
    CommonAPI
    CommonAPI-SomeIP
    vsomeip3
    ${CMAKE_CURRENT_SOURCE_DIR}/commonapi-wrappers/playground/lib/liborg.genivi.vehicle.playground.SomeIPCommon.so
    ${CMAKE_CURRENT_SOURCE_DIR}/commonapi-wrappers/playground/lib/liborg.genivi.vehicle.playground.SomeIPProxy.so
)

# 런타임에서 .so 찾기 쉽게 RPATH 박기 (LD_LIBRARY_PATH 의존 줄이기)
set_target_properties(PlaygroundClient PROPERTIES
    BUILD_RPATH
        "${CMAKE_CURRENT_SOURCE_DIR}/commonapi-wrappers/playground/lib;${CMAKE_CURRENT_SOURCE_DIR}/commonapi-wrappers/build;${HOME}/usr/lib;/usr/local/lib/commonapi"
    INSTALL_RPATH
        "${CMAKE_CURRENT_SOURCE_DIR}/commonapi-wrappers/playground/lib;${CMAKE_CURRENT_SOURCE_DIR}/commonapi-wrappers/build;${HOME}/usr/lib;/usr/local/lib/commonapi"
)

# -------------------------
# PlaygroundService
# -------------------------
add_executable(PlaygroundService
    src/PlaygroundService.cpp
    src/PlaygroundStubImpl.cpp
    src/mock/MockedAttributes.cpp
)

target_link_libraries(PlaygroundService
    Threads::Threads
    CommonAPI
    CommonAPI-SomeIP
    vsomeip3
    ${CMAKE_CURRENT_SOURCE_DIR}/commonapi-wrappers/playground/lib/liborg.genivi.vehicle.playground.SomeIPCommon.so
    ${CMAKE_CURRENT_SOURCE_DIR}/commonapi-wrappers/playground/lib/liborg.genivi.vehicle.playground.SomeIPStub.so
)
