import base64
import json
import os
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

URL = os.getenv("X_POST_URL", "https://x-service-69x7.onrender.com/mcp/create_post")
TEXT = "有些美，不必喧哗。\n一眼心动，便足以让寻常的时光，留下温柔的痕迹。"


def main():
    if len(sys.argv) < 2:
        print("用法: py local_image_post_test.py <图片路径>")
        print(r'例如: py local_image_post_test.py "D:\\01-个人文件\\X\\test.png"')
        raise SystemExit(2)

    image_path = sys.argv[1]
    if not os.path.isfile(image_path):
        print(f"图片不存在: {image_path}")
        raise SystemExit(2)

    with open(image_path, "rb") as f:
        image_base64 = base64.b64encode(f.read()).decode("ascii")

    payload = {
        "text": TEXT,
        "image_base64": image_base64,
        "image_filename": os.path.basename(image_path),
    }

    print("X image post test - AUTO CLICK ENABLED")
    print(f"URL: {URL}")
    print(f"IMAGE: {image_path}")
    print(f"TEXT: {TEXT}")
    print("服务器会执行：上传图片 -> 验证图片 -> 输入文字 -> 验证文字 -> 等待 Post 启用 -> 自动点击 Post")
    print("如果任一步验证失败，程序不会点击 Post。")

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        URL,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=120) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            print(f"HTTP {response.status}")
            print(response_body)
    except HTTPError as e:
        response_body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code}")
        print(response_body)
        raise SystemExit(1)
    except URLError as e:
        print(f"REQUEST ERROR: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
