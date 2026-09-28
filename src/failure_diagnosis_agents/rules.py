import math

OSF_THRESHOLD = {"L": 11000, "M": 12000, "H": 13000}


def check_twf(tool_wear_time: float) -> dict:
    # TWF는 200~240분 구간에서 "무작위로" 발생 — 이 구간에 있다고 반드시 고장은 아님.
    # 그래서 triggered=True는 "고장이다"가 아니라 "고장 가능 구간에 있다"는 뜻.
    in_risk_window = (tool_wear_time >= 200) and (tool_wear_time <= 240)
    return {"triggered": in_risk_window}


def check_hdf(air_temperature: float, process_temperature: float, rotational_speed: float) -> dict:
    temp_diff = process_temperature - air_temperature
    triggered = (temp_diff < 8.6) and (rotational_speed < 1380)
    return {"temp_diff": temp_diff, "triggered": triggered}


def check_pwf(torque: float, rotational_speed: float) -> dict:
    rotational_speed_rad_s = rotational_speed * 2 * math.pi / 60
    power = torque * rotational_speed_rad_s
    triggered = (power < 3500) or (power > 9000)
    return {"power": power, "triggered": triggered}


def check_osf(tool_wear_time: float, torque: float, type: str) -> dict:
    strain = tool_wear_time * torque
    threshold = OSF_THRESHOLD[type]
    triggered = strain > threshold
    return {"strain": strain, "threshold": threshold, "triggered": triggered}


def demo() -> None:
    # 실제 ai4i2020.csv에서 뽑은 행으로 검증 (UDI=3237: HDF=1, UDI=51: PWF=1, UDI=70: OSF·PWF=1, UDI=1: 전부 정상)
    assert check_hdf(300.8, 309.4, 1342)["triggered"] is True
    assert check_pwf(4.6, 2861)["triggered"] is True
    assert check_osf(191, 65.7, "L")["triggered"] is True
    assert check_pwf(65.7, 1410)["triggered"] is True

    assert check_twf(0)["triggered"] is False
    assert check_hdf(298.1, 308.6, 1551)["triggered"] is False
    assert check_pwf(42.8, 1551)["triggered"] is False
    assert check_osf(0, 42.8, "M")["triggered"] is False

    print("rules.py self-check passed")


if __name__ == "__main__":
    demo()
