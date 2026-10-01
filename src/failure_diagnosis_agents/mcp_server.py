from mcp.server.fastmcp import FastMCP

from failure_diagnosis_agents.rules import check_twf, check_hdf, check_pwf, check_osf

mcp = FastMCP("failure-diagnosis-rules")


@mcp.tool()
def twf_check(tool_wear_time: float) -> dict:
    """공구마모고장(TWF) 규칙 계산. 공구 누적 사용 시간(분)이 200~240분 구간인지 확인."""
    return check_twf(tool_wear_time)


@mcp.tool()
def hdf_check(air_temperature: float, process_temperature: float, rotational_speed: float) -> dict:
    """방열고장(HDF) 규칙 계산. (공정온도-대기온도)<8.6K AND 회전속도<1380rpm 인지 확인."""
    return check_hdf(air_temperature, process_temperature, rotational_speed)


@mcp.tool()
def pwf_check(torque: float, rotational_speed: float) -> dict:
    """동력고장(PWF) 규칙 계산. 토크×회전속도(동력, W)가 3500~9000W 범위를 벗어나는지 확인."""
    return check_pwf(torque, rotational_speed)


@mcp.tool()
def osf_check(tool_wear_time: float, torque: float, type: str) -> dict:
    """과응력고장(OSF) 규칙 계산. 공구마모시간×토크(응력)가 제품등급(L/M/H)별 임계치를 초과하는지 확인."""
    return check_osf(tool_wear_time, torque, type)


if __name__ == "__main__":
    mcp.run(transport="stdio")
