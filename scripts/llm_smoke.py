import asyncio

from dotenv import load_dotenv
from shared_llm.client import ask_llm


load_dotenv()


async def main() -> None:
    answer = await ask_llm(
        "Ответь одним коротким предложением: что такое API?",
        system_prompt="Отвечай кратко на русском языке.",
    )
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())
