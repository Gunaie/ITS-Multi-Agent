import os
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv('backend/app/.env')

async def test_model():
    api_key = os.getenv('AL_BAILIAN_API_KEY')
    base_url = os.getenv('AL_BAILIAN_BASE_URL')
    main_model = os.getenv('MAIN_MODEL_NAME')
    sub_model = os.getenv('SUB_MODEL_NAME')
    
    print(f"Testing models: {main_model}, {sub_model}")
    
    client = AsyncOpenAI(
        api_key=api_key,
        base_url=base_url
    )
    
    try:
        response = await client.chat.completions.create(
            model=main_model,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=10
        )
        print(f"Main model success: {response.choices[0].message.content}")
    except Exception as e:
        print(f"Main model failed: {e}")

    try:
        response = await client.chat.completions.create(
            model=sub_model,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=10
        )
        print(f"Sub model success: {response.choices[0].message.content}")
    except Exception as e:
        print(f"Sub model failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_model())
