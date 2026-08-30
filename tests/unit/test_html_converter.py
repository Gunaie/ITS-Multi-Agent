from markdownify import markdownify as md
import pytest

def test_html_to_markdown_conversion():
    """
    测试 HTML 内容是否能正确转换为 Markdown 格式
    """
    origin_html_content = """
    <html>
     <head></head>
     <body>
      <p><strong>解决方案</strong><strong>：</strong></p>
      <p>利用软碟通软件（UltraISO）实现</p>
      <p><img src="https://example.com/image.jpg" alt="test image"></p>
      <p><strong>注意事项：</strong>此操作会格式化所选择的U盘，操作一定谨慎！</p>
     </body>
    </html>
    """
    
    markdown_content = md(origin_html_content).strip()
    
    # 断言关键内容存在
    assert "**解决方案**" in markdown_content
    assert "利用软碟通软件（UltraISO）实现" in markdown_content
    assert "![test image](https://example.com/image.jpg)" in markdown_content
    assert "**注意事项：**" in markdown_content
