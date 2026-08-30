import re
import pytest

def test_illegal_filename_chars_replacement():
    """
    测试非法文件名字符替换逻辑
    """
    illegal_chars = r'[\\/:*?"<>|]'
    test_string = '如何解决开机蓝屏? (错误代码: 0x000007B)'
    
    # 替换非法字符为 -
    cleaned_string = re.sub(illegal_chars, '-', test_string)
    
    # 断言非法字符已被替换
    assert '?' not in cleaned_string
    assert ':' not in cleaned_string
    assert cleaned_string == '如何解决开机蓝屏- (错误代码- 0x000007B)'

def test_multiple_illegal_chars():
    illegal_chars = r'[\\/:*?"<>|]'
    test_string = r'a/b\c:d*e?f"g<h>i|j'
    cleaned_string = re.sub(illegal_chars, '-', test_string)
    assert cleaned_string == 'a-b-c-d-e-f-g-h-i-j'
