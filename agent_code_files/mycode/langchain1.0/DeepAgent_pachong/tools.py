import os
import json
import time
import random
import asyncio
import aiohttp
import traceback
import textwrap
import ast
from typing import Dict, Any, List
from collections import Counter

from langchain.tools import tool
from bs4 import BeautifulSoup
import agent_config as config

# ============================================
# 辅助函数
# ============================================

def write_file_sync(filepath: str, content: str):
    """同步写入文件 (用于 asyncio.to_thread)"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

def read_file_sync(filepath: str) -> str:
    """同步读取文件 (用于 asyncio.to_thread)"""
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()

def get_safe_headers(url: str) -> Dict[str, str]:
    """获取安全的请求头 (包含随机的高质量 Desktop UA)
    
    逻辑说明:
    1. 随机选择一个主流浏览器的 User-Agent (Chrome, Edge, Firefox, Safari) 以模拟真实用户。
    2. 设置标准的 Accept, Accept-Language 等头部信息。
    3. 特别注意 Accept-Encoding 包含 gzip, deflate 以支持压缩，但不包含 br (Brotli) 以免如果没有相应库导致解压失败。
    """
    pc_user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 Edg/122.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15"
    ]
    
    return {
        'User-Agent': random.choice(pc_user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'Referer': url,
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }

# ============================================
# WebAnalyzer 工具
# ============================================

@tool
async def fetch_url(url: str, use_selenium: bool = False) -> Dict[str, Any]:
    """获取网页内容
    
    思路梳理:
    1. **请求准备**: 生成随机 User-Agent 和安全请求头，防止被轻易识别为爬虫。
    2. **发送请求**: 使用 aiohttp 异步发送 GET 请求，设置 15秒超时。
    3. **处理响应**:
        - 检查是否发生了重定向。
        - 检查 HTTP 状态码，如果是 4xx/5xx 则抛出异常。
    4. **内容解码**: 尝试自动解码，如果失败 (UnicodeDecodeError) 则回退到 gbk 编码 (常见于中文老网站)。
    5. **文件持久化**: 将获取到的完整 HTML 内容保存到本地文件 (source_page.html)，供后续分析工具读取，避免大文本在 Agent 上下文中传递导致 Token 溢出。
    6. **返回结果**: 返回预览信息、文件路径和状态码。
    
    Args:
        url: 目标网址
        use_selenium: 是否使用 Selenium (用于动态网页)
    
    Returns:
        {"html_preview": "...", "html_file": "path/to/file", "status_code": 200, "success": True}
    """
    
    try:
        print(f"🌍 [fetch_url] 正在请求: {url}")

        # 1. 获取伪装的请求头
        headers = get_safe_headers(url)

        async with aiohttp.ClientSession() as session:
            # 2. 发起异步 GET 请求
            async with session.get(url, headers=headers, timeout=15) as response:
                
                final_url = str(response.url)
                if final_url != url:
                    print(f"⚠️ [fetch_url] 发生重定向: {url} -> {final_url}")
                else:
                    print(f"✅ [fetch_url] 请求成功: {final_url} (Status: {response.status})")

                if response.status >= 400:
                    response.raise_for_status()
                
                print(f"⬇️ [fetch_url] 正在下载响应内容...")
                # 3. 获取并解码文本内容
                try:
                    text = await response.text()
                except UnicodeDecodeError:
                    # 备用解码方案：针对 GBK/GB2312 编码的网站
                    text = await response.text(encoding='gbk', errors='ignore')
                print(f"✅ [fetch_url] 内容下载完成 ({len(text)} 字符)")

                # 4. 保存到文件 (关键步骤：避免 Context Window 爆炸)
                filename = "source_page.html"
                filepath = os.path.join(config.workspace_dir, filename)
                
                print(f"💾 [fetch_url] 正在保存文件: {filepath}")
                await asyncio.to_thread(write_file_sync, filepath, text)
                print(f"✅ [fetch_url] 文件保存完成")

                print(f"DEBUG: fetch_url constructing response...")
                # 5. 构造返回结果
                result = {
                    "html_preview": text[:1000] + "... (完整内容已保存到文件)",
                    "html_file": filepath,
                    "status_code": response.status,
                    "url": final_url,
                    "encoding": response.get_encoding(),
                    "success": True,
                    "error": None
                }
                print(f"DEBUG: fetch_url returning response...")
                return result
    except Exception as e:
        return {
            "html_preview": "",
            "html_file": "",
            "status_code": 0,
            "url": url,
            "success": False,
            "error": str(e)
        }

@tool
async def analyze_html_structure(html: str = "", html_file: str = "", url: str = "") -> Dict[str, Any]:
    """分析 HTML 结构，识别数据元素

    思路梳理:
    1. **读取内容**: 优先从文件读取 HTML 内容 (因为 fetch_url 会保存文件)，如果未提供文件则使用传入的 html 字符串。
    2. **解析 DOM**: 使用 BeautifulSoup (lxml 解析器) 解析 HTML。
    3. **基础信息提取**: 提取网页标题、统计标签分布 (Tag Distribution) 以了解页面复杂度。
    4. **容器识别 (关键)**: 
        - 扫描常见的容器标签 (div, article, section, li)。
        - 提取其 class 属性和文本预览，帮助 LLM 识别列表项 (List Items) 的特征。
    5. **样本提取**: 提取部分链接 (a) 和图片 (img) 作为样本，供 LLM 分析 URL 模式。
    6. **分页检测**: 简单的关键词匹配 (next, 下一页) 来推测是否存在分页机制。
    7. **返回 JSON**: 将所有分析结果打包成 JSON 格式返回给 LLM。

    Args:
        html: HTML 内容 (可选)
        html_file: HTML 文件路径 (可选，推荐)
        url: 原始 URL（可选）

    Returns:
        结构化的分析结果
    """
    print(f"DEBUG: analyze_html_structure called with file={html_file}", flush=True)
    try:
        content = html
        # 1. 优先读取文件
        if html_file and os.path.exists(html_file):
            with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        
        if not content:
            return {"success": False, "error": "No HTML content provided"}
            
        # 2. 初始化 BeautifulSoup
        soup = BeautifulSoup(content, 'lxml')

        title = soup.title.string if soup.title else ""

        # 3. 统计标签分布
        all_tags = [tag.name for tag in soup.find_all()]
        tag_counter = Counter(all_tags)

        # 4. 识别通用容器 (寻找列表项模式)
        common_containers = []
        for tag in ['div', 'article', 'section', 'li']:
            elements = soup.find_all(tag, class_=True)
            for elem in elements[:5]: # 仅取前5个样本
                classes = ' '.join(elem.get('class', []))
                if classes:
                    common_containers.append({
                        'tag': tag,
                        'class': classes,
                        'text_preview': elem.get_text()[:50].strip()
                    })

        # 5. 提取链接样本
        links = []
        for a in soup.find_all('a', href=True)[:10]:
            links.append({
                'href': a['href'],
                'text': a.get_text().strip()[:30]
            })

        # 6. 提取图片样本
        images = []
        for img in soup.find_all('img', src=True)[:10]:
            images.append({
                'src': img['src'],
                'alt': img.get('alt', '')[:30]
            })

        # 7. 组装分析报告
        analysis = json.dumps({
            "title": title,
            "url": url,
            "total_tags": len(all_tags),
            "tag_distribution": dict(tag_counter.most_common(10)),
            "links_count": len(soup.find_all('a')),
            "images_count": len(soup.find_all('img')),
            "common_containers": common_containers[:10],
            "sample_links": links,
            "sample_images": images,
            "has_pagination": bool(soup.find_all(['a', 'button'], string=lambda t: t and ('next' in t.lower() or '下一页' in t))),
            "success": True
        }
        )

        return analysis

    except Exception as e:
        return json.dumps({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        })

@tool
async def detect_anti_scraping(url: str, html: str = "", html_file: str = "") -> Dict[str, Any]:
    """检测反爬虫机制

    思路梳理:
    1. **加载内容**: 同样优先从文件读取 HTML。
    2. **关键词匹配**:
        - 检查是否包含 "cloudflare" -> 可能有 5秒盾或 WAF。
        - 检查 "captcha", "recaptcha", "验证码" -> 存在人机验证。
    3. **启发式检测**:
        - 如果页面包含 script 标签但文本内容极少 (<500字符) -> 可能是纯 JS 渲染页面 (SPA)，需要 Selenium/Playwright。
    4. **生成建议**: 根据检测结果提供相应的反爬策略建议 (如使用 cloudscraper, 增加延迟, 切换 User-Agent)。

    Args:
        url: 目标网址
        html: HTML 内容（可选）
        html_file: HTML 文件路径（可选，推荐）

    Returns:
        反爬虫检测结果和建议
    """

    try:
        content = html
        if html_file and os.path.exists(html_file):
            with open(html_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        # 定义建议列表
        recommendations = []

        # 定义检测到的反爬机制列表
        detected_mechanisms = []

        if content:
            soup = BeautifulSoup(content, 'lxml')

            # 检测 Cloudflare
            if 'cloudflare' in content.lower():
                detected_mechanisms.append("Cloudflare")
                recommendations.append("使用 cloudscraper 库")

            # 检测验证码
            if any(keyword in content.lower() for keyword in ['captcha', 'recaptcha', '验证码']):
                detected_mechanisms.append("CAPTCHA")
                recommendations.append("需要人工验证或使用验证码识别服务")

            # 检测 JS 渲染 (内容过短且有大量脚本)
            if soup.find_all('script') and len(soup.get_text().strip()) < 500:
                detected_mechanisms.append("JavaScript Rendering")
                recommendations.append("使用 Selenium 或 Playwright")

        # 默认建议
        if not recommendations:
            recommendations = [
                "添加随机延迟 (1-3秒)",
                "使用随机 User-Agent",
                "设置合理的请求头"
            ]

        return {
            "url": url,
            "detected_mechanisms": detected_mechanisms,
            "has_anti_scraping": len(detected_mechanisms) > 0,
            "recommendations": recommendations,
            "success": True
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

# ============================================
# CodeGenerator 工具
# ============================================

@tool
async def generate_spider_code(
    analysis: str,
    target_url: str,
    framework: str = "requests"
) -> Dict[str, Any]:
    """生成爬虫代码并保存到文件
    
    思路梳理:
    1. **解析输入**: 接收来自 WebAnalyzer 的分析结果 JSON。
    2. **选择模板**: 根据 `framework` 参数选择代码模板。
    3. **填充模板**: 将 `target_url` 注入到模板中。
    4. **保存代码**: 将生成的代码写入 `spider.py` 文件。
    
    Args:
        analysis: WebAnalyzer 的分析结果（JSON字符串）
        target_url: 目标网址
        framework: 使用的框架 (requests/selenium)
    
    Returns:
        包含文件路径和代码预览的字典
    """
    try:
        # 1. 解析分析结果
        if isinstance(analysis, str):
            try:
                analysis_dict = json.loads(analysis)
            except json.JSONDecodeError:
                analysis_dict = {}
        else:
            analysis_dict = analysis
        
        target_url = target_url.replace('`', '').strip()
        
        # 2. 生成 Requests 框架代码 (生产级模板)
        if framework == "requests":
            code = f'''
        #!/usr/bin/env python3
        # -*- coding: utf-8 -*-
        """
        自动生成的生产级爬虫
        目标网站: {target_url}
        生成时间: {time.strftime("%Y-%m-%d %H:%M:%S")}
        """

        import requests
        from bs4 import BeautifulSoup
        import json
        import time
        import random
        import logging
        from typing import Dict, List, Optional, Any
        from dataclasses import dataclass, asdict
        from datetime import datetime
        import sys
        import os

        # 配置日志
        def setup_logger():
            """设置日志配置"""
            logger = logging.getLogger('spider')
            logger.setLevel(logging.INFO)
            
            # 创建控制台处理器
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            
            # 创建文件处理器
            file_handler = logging.FileHandler('spider.log', encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            
            # 设置日志格式
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            console_handler.setFormatter(formatter)
            file_handler.setFormatter(formatter)
            
            # 添加处理器
            logger.addHandler(console_handler)
            logger.addHandler(file_handler)
            
            return logger

        logger = setup_logger()

        @dataclass
        class ItemData:
            """数据模型"""
            title: str
            url: str
            # TODO: 添加更多字段

        class BaseSpider:
            """爬虫基类"""
            
            def __init__(self):
                self.base_url = "{target_url}"
                self.session = requests.Session()
                self.setup_headers()
                self.setup_session()
                
            def setup_headers(self):
                """设置请求头"""
                self.headers = {{
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }}
                
            def setup_session(self):
                """设置会话"""
                self.session.headers.update(self.headers)
                self.session.timeout = 30
                
            def random_delay(self, min_seconds=1, max_seconds=3):
                """随机延迟"""
                delay = random.uniform(min_seconds, max_seconds)
                logger.debug(f"等待 {{delay:.2f}} 秒...")
                time.sleep(delay)
                
            def fetch_page(self, url: str) -> Optional[str]:
                """获取页面内容"""
                try:
                    logger.info(f"正在请求页面: {{url}}")
                    self.random_delay()
                    
                    response = self.session.get(url, headers=self.headers)
                    response.raise_for_status()
                    
                    if response.encoding is None:
                        response.encoding = 'utf-8'
                        
                    logger.info(f"页面请求成功，状态码: {{response.status_code}}")
                    return response.text
                    
                except Exception as e:
                    logger.error(f"请求页面失败: {{e}}")
                    return None
            
            def parse_data(self, soup: BeautifulSoup) -> List[ItemData]:
                """解析数据"""
                logger.info("开始解析数据...")
                items = []
                
                try:
                    # 示例：查找所有链接
                    # TODO: 根据实际需求修改选择器
                    links = soup.find_all('a', href=True)
                    logger.info(f"找到 {{len(links)}} 个链接")
                    
                    for link in links:
                        try:
                            title = link.get_text(strip=True)
                            url = link['href']
                            
                            if title and len(title) > 1:
                                item = ItemData(title=title, url=url)
                                items.append(item)
                        except Exception as e:
                            continue
                            
                except Exception as e:
                    logger.error(f"解析数据出错: {{e}}")
                    
                return items
            
            def save_to_json(self, data: List[ItemData], filename: str = None):
                """保存数据为JSON格式"""
                if filename is None:
                    filename = "scraped_data.json"
                
                try:
                    serializable_data = [asdict(item) for item in data]
                    
                    with open(filename, 'w', encoding='utf-8') as f:
                        json.dump(serializable_data, f, ensure_ascii=False, indent=2)
                    
                    logger.info(f"数据已保存到: {{filename}}")
                    return filename
                    
                except Exception as e:
                    logger.error(f"保存JSON文件时出错: {{e}}")
                    return None
            
            def run(self):
                """运行爬虫"""
                logger.info("=" * 50)
                logger.info("开始执行爬虫")
                logger.info("=" * 50)
                
                html_content = self.fetch_page(self.base_url)
                if not html_content:
                    return None
                
                soup = BeautifulSoup(html_content, 'lxml')
                data = self.parse_data(soup)
                
                self.save_to_json(data)
                
                logger.info("=" * 50)
                logger.info(f"爬取完成，共获取 {{len(data)}} 条数据")
                logger.info("=" * 50)
                
                return data

        def main():
            """主函数"""
            try:
                spider = BaseSpider()
                data = spider.run()
                
                if data:
                    return 0
                else:
                    return 1
                    
            except KeyboardInterrupt:
                logger.info("用户中断")
                return 130
            except Exception as e:
                logger.error(f"未预期错误: {{e}}")
                return 1

        if __name__ == "__main__":
            sys.exit(main())
                    '''
        else:
            # 3. 生成 Selenium 框架代码 (备用)
            code = f'''
            """
            自动生成的爬虫代码 (Selenium)
            目标网站: {target_url}
            """
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            import json
            import time


            def scrape_data(url):
                """使用 Selenium 爬取数据"""
                options = webdriver.ChromeOptions()
                options.add_argument('--headless')
                options.add_argument('--no-sandbox')
                
                driver = webdriver.Chrome(options=options)
                
                try:
                    print(f"正在访问: {{url}}")
                    driver.get(url)
                    
                    # 等待页面加载
                    time.sleep(3)
                    
                    # 提取数据
                    results = []
                    
                    # TODO: 根据网站结构提取数据
                    elements = driver.find_elements(By.TAG_NAME, 'a')
                    for elem in elements:
                        item = {{
                            'text': elem.text.strip(),
                            'url': elem.get_attribute('href')
                        }}
                        results.append(item)
                    
                    print(f"成功提取 {{len(results)}} 条数据")
                    return results
                    
                except Exception as e:
                    print(f"爬取失败: {{e}}")
                    return []
                finally:
                    driver.quit()


            def main():
                target_url = "{target_url}"
                data = scrape_data(target_url)
                
                if data:
                    with open("scraped_data.json", 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    print("数据已保存")


            if __name__ == "__main__":
                main()
            '''
        
        final_code = textwrap.dedent(code).strip()
        
        # 4. 保存文件
        try:
            os.makedirs(config.workspace_dir, exist_ok=True)
            file_path = os.path.join(config.workspace_dir, "spider.py")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(final_code)
        except Exception as e:
            print(f"⚠️ 保存代码文件失败: {e}")
            return {
                "success": False,
                "error": f"保存代码文件失败: {e}"
            }
            
        return {
            "success": True,
            "file_path": file_path,
            "code_preview": final_code[:500] + "\n... (完整代码已保存)",
            "message": "代码已生成并保存"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"代码生成失败: {str(e)}",
            "traceback": traceback.format_exc()
        }

@tool
async def validate_code_syntax(code: str) -> Dict[str, Any]:
    """验证 Python 代码语法
    
    思路梳理:
    1. 使用 Python 内置的 `ast.parse` 解析代码。
    2. 如果抛出 `SyntaxError`，捕获异常并返回具体的行号和错误信息。
    3. 如果没有异常，则认为语法有效。
    
    Args:
        code: Python 代码字符串
    
    Returns:
        验证结果
    """
    
    try:
        cleaned_code = textwrap.dedent(code).strip()
        ast.parse(cleaned_code)
        return {
            "valid": True,
            "errors": [],
            "message": "代码语法正确"
        }
    except SyntaxError as e:
        return {
            "valid": False,
            "errors": [{
                "line": e.lineno,
                "message": e.msg,
                "text": e.text
            }],
            "message": f"语法错误: {e.msg}"
        }
    except Exception as e:
        return {
            "valid": False,
            "errors": [str(e)],
            "message": f"验证失败: {str(e)}"
        }

@tool
async def save_spider_code(code: str, filename: str = "spider.py") -> str:
    """保存爬虫代码到文件
    
    思路梳理:
    1. 去除代码前后缩进和空白。
    2. 确保工作目录存在。
    3. 将代码写入指定文件 (默认 utf-8 编码)。
    
    Args:
        code: 完整的 Python 代码
        filename: 文件名 (默认 spider.py)
    
    Returns:
        保存结果信息
    """
    try:
        final_code = textwrap.dedent(code).strip()
        
        file_path = os.path.join(config.workspace_dir, filename)
        os.makedirs(config.workspace_dir, exist_ok=True)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(final_code)
            
        return f"✅ 代码已成功保存到: {file_path}"
    except Exception as e:
        return f"❌ 保存代码失败: {str(e)}"

# ============================================
# DebugAgent 工具
# ============================================

@tool
async def parse_error(error_message: str, code: str = "") -> Dict[str, Any]:
    """分析错误信息，提供修复建议
    
    思路梳理:
    1. **错误归类**: 根据错误信息中的关键词 (case-insensitive) 将错误归类。
        - NetworkError: connection, timeout, network
        - ParseError: parse, beautifulsoup, lxml
        - PermissionError: 403, forbidden, 401
        - NotFoundError: 404
        - EncodingError: encode, decode, unicode
        - ImportError: import, module
    2. **生成建议**: 针对每一类错误，提供预定义的修复建议列表 (如增加超时、更换 UA、检查选择器)。
    3. **返回结构化数据**: 供 Agent 决策使用。

    Args:
        error_message: 错误信息
        code: 出错的代码（可选）
    
    Returns:
        错误分析和修复建议
    """
    error_lower = error_message.lower()
    
    error_type = "Unknown"
    cause = ""
    suggestions = []
    
    # 1. 网络类错误
    if any(keyword in error_lower for keyword in ['connection', 'timeout', 'network']):
        error_type = "NetworkError"
        cause = "网络连接问题"
        suggestions = [
            "增加超时时间 (timeout=30)",
            "添加重试逻辑",
            "检查网络连接",
            "使用代理"
        ]
    
    # 2. 解析类错误
    elif any(keyword in error_lower for keyword in ['parse', 'beautifulsoup', 'lxml']):
        error_type = "ParseError"
        cause = "HTML 解析失败"
        suggestions = [
            "检查 HTML 内容是否完整",
            "尝试使用不同的解析器 (html.parser/lxml)",
            "检查选择器是否正确"
        ]
    
    # 3. 权限类错误 (反爬虫)
    elif any(keyword in error_lower for keyword in ['403', 'forbidden', '401', 'unauthorized']):
        error_type = "PermissionError"
        cause = "访问被拒绝"
        suggestions = [
            "添加或更换 User-Agent",
            "添加 Cookie 或认证信息",
            "降低请求频率",
            "使用代理 IP"
        ]
    
    # 4. 资源不存在
    elif '404' in error_lower:
        error_type = "NotFoundError"
        cause = "页面不存在"
        suggestions = [
            "检查 URL 是否正确",
            "检查页面是否已被删除或移动"
        ]
    
    # 5. 编码错误
    elif any(keyword in error_lower for keyword in ['encode', 'decode', 'unicode']):
        error_type = "EncodingError"
        cause = "字符编码问题"
        suggestions = [
            "指定正确的编码 (utf-8/gbk)",
            "使用 errors='ignore' 忽略错误字符"
        ]
    
    # 6. 依赖错误
    elif 'import' in error_lower or 'module' in error_lower:
        error_type = "ImportError"
        cause = "模块导入失败"
        suggestions = [
            "安装缺失的依赖包",
            "检查包名是否正确"
        ]
    
    else:
        suggestions = [
            "检查代码逻辑",
            "添加异常处理",
            "查看完整的错误堆栈"
        ]
    
    return {
        "error_type": error_type,
        "cause": cause,
        "suggestions": suggestions,
        "original_error": error_message[:500]
    }

# ============================================
# DataProcessor 工具
# ============================================

@tool
async def clean_data(raw_data: str) -> str:
    """清洗数据：去除空值、格式化、去重
    
    思路梳理:
    1. **数据加载**: 支持传入 JSON 字符串或文件路径。如果传入的是文件路径，先尝试读取文件。
    2. **标准化**: 将数据统一转换为列表格式。
    3. **去重与清洗**:
        - 遍历每条数据。
        - 移除值为空的字段 (None, "", [], {})。
        - 使用 JSON 字符串序列化作为去重键 (Seen Set)。
    4. **结果保存**: 将清洗后的数据保存到 `cleaned_data.json`。
    
    Args:
        raw_data: 原始数据（JSON字符串 或 文件路径）
    
    Returns:
        清洗后的数据（JSON字符串）
    """
    try:
        # 1. 加载数据
        if isinstance(raw_data, str):
            if os.path.exists(raw_data) and (raw_data.endswith('.json') or os.path.isfile(raw_data)):
                try:
                    with open(raw_data, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except:
                    data = json.loads(raw_data)
            else:
                data = json.loads(raw_data)
        else:
            data = raw_data
        
        # 2. 统一格式
        if not isinstance(data, list):
            data = [data]
        
        cleaned = []
        seen = set()
        
        # 3. 清洗循环
        for item in data:
            if not item:
                continue
            
            # 移除空字段
            cleaned_item = {k: v for k, v in item.items() if v}
            
            # 去重
            item_str = json.dumps(cleaned_item, sort_keys=True)
            if item_str not in seen:
                seen.add(item_str)
                cleaned.append(cleaned_item)
        
        result_json = json.dumps(cleaned, ensure_ascii=False, indent=2)
        
        # 4. 保存结果
        try:
            os.makedirs(config.workspace_dir, exist_ok=True)
            with open(os.path.join(config.workspace_dir, "cleaned_data.json"), "w", encoding="utf-8") as f:
                f.write(result_json)
        except Exception as e:
            print(f"⚠️ 保存清洗数据失败: {e}")
            
        return result_json
        
    except Exception as e:
        return json.dumps({"error": str(e)})

@tool
async def validate_data(data: str, required_fields: List[str] = None) -> Dict[str, Any]:
    """验证数据完整性
    
    思路梳理:
    1. **数据准备**: 解析输入的 JSON 数据。
    2. **规则校验**: 如果指定了 `required_fields`，则遍历所有记录，检查这些字段是否存在且非空。
    3. **统计问题**: 记录验证失败的记录索引和缺失字段。
    4. **返回报告**: 返回验证是否通过 (valid)，以及详细的统计信息 (总数、有效数、无效数、问题样本)。
    
    Args:
        data: 数据（JSON字符串）
        required_fields: 在数据中必须包含的字段列表，判断该字段是否为空
    
    Returns:
        验证结果
    """
    try:
        if isinstance(data, str):
            data_list = json.loads(data)
        else:
            data_list = data
        
        if not isinstance(data_list, list):
            data_list = [data_list]
        
        total_records = len(data_list)
        invalid_records = 0
        issues = []
        
        if required_fields:
            for i, item in enumerate(data_list):
                # 检查缺失字段
                missing_fields = [f for f in required_fields if f not in item or not item[f]]
                if missing_fields:
                    invalid_records += 1
                    issues.append({
                        "record_index": i,
                        "missing_fields": missing_fields
                    })
        
        return {
            "valid": invalid_records == 0,
            "total_records": total_records,
            "valid_records": total_records - invalid_records,
            "invalid_records": invalid_records,
            "issues": issues[:10]
        }
        
    except Exception as e:
        return {
            "valid": False,
            "error": str(e)
        }
