
import subprocess
import os
import sys
import time
import signal
import io

# 强制设置输出编码为 UTF-8 以支持 Emoji
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 定义所有服务的启动配置
SERVICES = [
    {
        "name": "Knowledge API (8001)",
        "cwd": os.path.join(os.getcwd(), "backend", "knowledge"),
        "command": ["uv", "run", "python", os.path.join(os.getcwd(), "backend", "knowledge", "api", "main.py")],
        "env_add": {"PYTHONPATH": os.path.join(os.getcwd(), "backend", "knowledge")}
    },
    {
        "name": "App Backend (8002)",
        "cwd": os.path.join(os.getcwd(), "backend", "app"),
        "command": ["uv", "run", "python", os.path.join(os.getcwd(), "backend", "app", "main.py")],
        "env_add": {"PYTHONPATH": os.path.join(os.getcwd(), "backend", "app")}
    },
    {
        "name": "Knowledge UI (3000)",
        "cwd": os.path.join(os.getcwd(), "front", "knowlege_platform_ui"),
        "command": ["npm.cmd" if os.name == 'nt' else "npm", "run", "dev"]
    },
    {
        "name": "Agent UI (3002)",
        "cwd": os.path.join(os.getcwd(), "front", "agent_web_ui"),
        "command": ["npm.cmd" if os.name == 'nt' else "npm", "run", "dev"]
    }
]

processes = []

def signal_handler(sig, frame):
    print("\nStopping all services...")
    for p, name in processes:
        print(f"Stopping {name}...")
        if os.name == 'nt':
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
        else:
            p.terminate()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def start_services():
    print("Starting ITS Multi-Agent Project Development Environment...")
    
    for service in SERVICES:
        print(f"Starting {service['name']}...")
        env = os.environ.copy()
        if "env_add" in service:
            for k, v in service["env_add"].items():
                env[k] = v + (os.pathsep + env.get(k, "") if env.get(k) else "")
        
        p = subprocess.Popen(
            service["command"],
            cwd=service["cwd"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8', # 强制使用 utf-8 读取子进程输出
            errors='replace', # 遇到解码错误时替换
            bufsize=1,
            shell=True if os.name == 'nt' else False
        )
        processes.append((p, service["name"]))
        time.sleep(1)

    print("\nAll services started!")
    print("---------------------------------------")
    print("Knowledge API: http://127.0.0.1:8001")
    print("App Backend:   http://127.0.0.1:8002")
    print("Knowledge UI:  http://localhost:3000")
    print("Agent UI:      http://localhost:3002")
    print("---------------------------------------")
    print("Tip: Press Ctrl+C to stop all services.\n")

    # 循环读取输出并打印（简单实现，主要看是否报错）
    while True:
        for p, name in processes:
            line = p.stdout.readline()
            if line:
                print(f"[{name}] {line.strip()}")
            if p.poll() is not None:
                print(f"❌ {name} 已退出，退出码: {p.returncode}")
                # 如果某个核心服务退出了，可能需要处理
        time.sleep(0.01)

if __name__ == "__main__":
    try:
        start_services()
    except KeyboardInterrupt:
        signal_handler(None, None)
