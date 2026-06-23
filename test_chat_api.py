from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()
base_url = "https://api.uniapi.io/v1"
api_key = os.getenv("UNIAPI_API_KEY")

print(f"API Key: {api_key[:20]}...")
print(f"Base URL: {base_url}")
print()

client = OpenAI(base_url=base_url, api_key=api_key)

# 测试 1: 简单英文
print("Test 1: Simple English")
response = client.chat.completions.create(
  model="glm-5.2",
  messages=[
    {
      "role": "user",
      "content": "Write a one-sentence bedtime story about a unicorn."
    }
  ]
)
print(f"Response: {response.choices[0].message.content[:100]}")
print()

# 测试 2: 中文
print("Test 2: Chinese")
response = client.chat.completions.create(
  model="glm-5.2",
  messages=[
    {
      "role": "user",
      "content": "写一个关于独角兽的一句话睡前故事。"
    }
  ]
)
print(f"Response: {response.choices[0].message.content[:100]}")
print()

# 测试 3: 长中文
print("Test 3: Long Chinese")
response = client.chat.completions.create(
  model="glm-5.2",
  messages=[
    {
      "role": "user",
      "content": "一个机场航站楼出发大厅的室内场景，采用斜侧广角视角。"
    }
  ]
)
print(f"Response: {response.choices[0].message.content[:100]}")
