import asyncio

from langchain_mcp_adapters.client import MultiServerMCPClient

client = MultiServerMCPClient(
    {
        "rules": {
            "command": "python",  # 1. 이 명령어로 서버 프로세스를 띄움
            "args": ["-m", "failure_diagnosis_agents.mcp_server"],
            "transport": "stdio",
        }
    }
)


async def main() -> None:
    tools = await client.get_tools()  # 2. 서버에 접속해서 등록된 툴 목록을 LangChain 툴로 변환해 받아옴
    for tool in tools:
        print(tool.name, "-", tool.description)

    # 3. 실제로 툴 하나를 호출해봄 (LLM 없이, 순수 연결 확인용)
    twf_tool = next(t for t in tools if t.name == "twf_check")
    result = await twf_tool.ainvoke({"tool_wear_time": 220})
    print("twf_check(220) ->", result)


if __name__ == "__main__":
    asyncio.run(main())
