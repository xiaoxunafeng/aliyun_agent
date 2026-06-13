#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
豆瓣电影首页爬虫 - 生产级实现
基于豆瓣电影网站分析报告生成
"""

import json
import logging
import random
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


@dataclass
class MovieInfo:
    """电影信息数据模型"""
    title: str  # 电影标题
    rating: Optional[float] = None  # 评分，可能为None
    url: str = ""  # 电影链接
    poster_url: Optional[str] = None  # 海报链接
    director: Optional[str] = None  # 导演
    actors: Optional[str] = None  # 演员
    duration: Optional[str] = None  # 时长
    region: Optional[str] = None  # 地区
    release_year: Optional[str] = None  # 上映年份
    rater_count: Optional[int] = None  # 评分人数
    star_level: Optional[str] = None  # 星级
    extracted_at: str = field(default_factory=lambda: datetime.now().isoformat())  # 提取时间

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，处理特殊类型"""
        data = asdict(self)
        # 处理datetime序列化
        if 'extracted_at' in data and isinstance(data['extracted_at'], datetime):
            data['extracted_at'] = data['extracted_at'].isoformat()
        return data


class DoubanMovieSpider:
    """豆瓣电影爬虫 - 生产级实现"""

    def __init__(self, base_url: str = "https://movie.douban.com/"):
        """
        初始化爬虫

        Args:
            base_url: 豆瓣电影基础URL
        """
        self.base_url = base_url
        self.session = requests.Session()
        self.logger = self._setup_logging()
        self.movies: List[MovieInfo] = []

        # 配置请求头
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',  # 严禁包含 'br'
            'Connection': 'keep-alive',
            'Referer': 'https://www.douban.com/',
            'Upgrade-Insecure-Requests': '1',
        }

        # User-Agent池
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
        ]

        self.logger.info(f"豆瓣电影爬虫初始化完成，目标URL: {base_url}")

    def _setup_logging(self) -> logging.Logger:
        """配置日志系统"""
        logger = logging.getLogger('DoubanMovieSpider')
        logger.setLevel(logging.INFO)

        # 避免重复添加handler
        if not logger.handlers:
            # 控制台handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(console_format)
            logger.addHandler(console_handler)

            # 文件handler
            try:
                file_handler = logging.FileHandler('/workspace/douban_spider.log', encoding='utf-8')
                file_handler.setLevel(logging.DEBUG)
                file_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
                file_handler.setFormatter(file_format)
                logger.addHandler(file_handler)
            except Exception as e:
                logger.warning(f"无法创建日志文件: {e}")

        return logger

    def random_delay(self, min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
        """
        随机延迟，避免请求过于频繁

        Args:
            min_seconds: 最小延迟秒数
            max_seconds: 最大延迟秒数
        """
        delay = random.uniform(min_seconds, max_seconds)
        self.logger.debug(f"随机延迟 {delay:.2f} 秒")
        time.sleep(delay)

    def rotate_user_agent(self) -> None:
        """轮换User-Agent"""
        new_agent = random.choice(self.user_agents)
        self.headers['User-Agent'] = new_agent
        self.logger.debug(f"切换User-Agent: {new_agent[:50]}...")

    def fetch_page(self, url: str) -> Optional[str]:
        """
        获取页面内容

        Args:
            url: 目标URL

        Returns:
            页面HTML内容或None（如果请求失败）
        """
        try:
            # 轮换User-Agent
            self.rotate_user_agent()

            # 添加随机延迟
            self.random_delay()

            self.logger.info(f"正在请求页面: {url}")
            response = self.session.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()

            # 检查编码
            if response.encoding != 'utf-8':
                response.encoding = 'utf-8'

            self.logger.info(f"页面请求成功，状态码: {response.status_code}")
            return response.text

        except requests.exceptions.RequestException as e:
            self.logger.error(f"请求页面失败: {url}, 错误: {e}")
            return None
        except Exception as e:
            self.logger.error(f"获取页面时发生未知错误: {e}")
            return None

    def parse_movie_item(self, movie_item) -> Optional[MovieInfo]:
        """
        解析单个电影项目

        Args:
            movie_item: BeautifulSoup元素

        Returns:
            MovieInfo对象或None（如果解析失败）
        """
        try:
            # 防御性检查
            if not movie_item:
                self.logger.warning("电影项目为空")
                return None

            # 优先从data-*属性提取数据
            data_title = movie_item.get('data-title', '').strip()
            data_rate = movie_item.get('data-rate', '').strip()
            data_director = movie_item.get('data-director', '').strip()
            data_actors = movie_item.get('data-actors', '').strip()
            data_duration = movie_item.get('data-duration', '').strip()
            data_region = movie_item.get('data-region', '').strip()
            data_release = movie_item.get('data-release', '').strip()
            data_rater = movie_item.get('data-rater', '').strip()
            data_star = movie_item.get('data-star', '').strip()

            # 提取电影链接
            link_elem = movie_item.select_one('.title a')
            movie_url = link_elem.get('href', '').strip() if link_elem else ''

            # 处理相对URL
            if movie_url and not movie_url.startswith('http'):
                movie_url = urljoin(self.base_url, movie_url)

            # 提取海报链接
            poster_elem = movie_item.select_one('.poster img')
            poster_url = poster_elem.get('src', '').strip() if poster_elem else None

            # 处理评分
            rating = None
            if data_rate:
                try:
                    rating = float(data_rate)
                except ValueError:
                    # 尝试从文本提取
                    rating_elem = movie_item.select_one('.subject-rate')
                    if rating_elem and rating_elem.text.strip():
                        try:
                            rating = float(rating_elem.text.strip())
                        except ValueError:
                            pass

            # 处理评分人数
            rater_count = None
            if data_rater:
                try:
                    rater_count = int(data_rater)
                except ValueError:
                    pass

            # 创建电影信息对象
            movie_info = MovieInfo(
                title=data_title if data_title else self._extract_title_from_text(movie_item),
                rating=rating,
                url=movie_url,
                poster_url=poster_url,
                director=data_director if data_director else None,
                actors=data_actors if data_actors else None,
                duration=data_duration if data_duration else None,
                region=data_region if data_region else None,
                release_year=data_release if data_release else None,
                rater_count=rater_count,
                star_level=data_star if data_star else None,
            )

            self.logger.debug(f"成功解析电影: {movie_info.title}")
            return movie_info

        except Exception as e:
            self.logger.error(f"解析电影项目时发生错误: {e}", exc_info=True)
            return None

    def _extract_title_from_text(self, movie_item) -> str:
        """从文本提取电影标题（备用方法）"""
        try:
            title_elem = movie_item.select_one('.title a')
            if title_elem and title_elem.text.strip():
                return title_elem.text.strip()

            # 尝试其他选择器
            for selector in ['.title', 'h3', 'h4']:
                elem = movie_item.select_one(selector)
                if elem and elem.text.strip():
                    return elem.text.strip()

            return "未知标题"
        except Exception:
            return "未知标题"

    def parse_homepage(self, html_content: str) -> List[MovieInfo]:
        """
        解析豆瓣电影首页

        Args:
            html_content: 页面HTML内容

        Returns:
            电影信息列表
        """
        movies = []

        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # 查找正在热映区域
            screening_section = soup.select_one('#screening')
            if not screening_section:
                self.logger.warning("未找到正在热映区域 (#screening)")
                return movies

            # 查找电影列表容器
            movie_list_container = screening_section.select_one('.screening-bd .ui-slide-content')
            if not movie_list_container:
                self.logger.warning("未找到电影列表容器")
                return movies

            # 查找所有电影项目
            movie_items = movie_list_container.select('.ui-slide-item')
            self.logger.info(f"找到 {len(movie_items)} 个电影项目")

            # 解析每个电影项目
            for i, movie_item in enumerate(movie_items):
                try:
                    movie_info = self.parse_movie_item(movie_item)
                    if movie_info:
                        movies.append(movie_info)
                        self.logger.debug(f"成功解析第 {i+1} 个电影: {movie_info.title}")
                    else:
                        self.logger.warning(f"第 {i+1} 个电影项目解析失败")
                except Exception as e:
                    self.logger.error(f"解析第 {i+1} 个电影时发生错误: {e}")
                    continue

            self.logger.info(f"成功解析 {len(movies)} 部电影")

        except Exception as e:
            self.logger.error(f"解析首页时发生错误: {e}", exc_info=True)

        return movies

    def save_to_json(self, filename: str = "/workspace/douban_movies.json") -> bool:
        """
        保存电影数据到JSON文件

        Args:
            filename: 输出文件名

        Returns:
            保存是否成功
        """
        try:
            if not self.movies:
                self.logger.warning("没有电影数据可保存")
                return False

            # 转换为字典列表
            movies_data = [movie.to_dict() for movie in self.movies]

            # 准备保存的数据
            output_data = {
                "metadata": {
                    "source": "豆瓣电影首页",
                    "url": self.base_url,
                    "extracted_at": datetime.now().isoformat(),
                    "movie_count": len(self.movies)
                },
                "movies": movies_data
            }

            # 保存到文件
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)

            self.logger.info(f"成功保存 {len(self.movies)} 部电影数据到 {filename}")
            return True

        except Exception as e:
            self.logger.error(f"保存数据到JSON时发生错误: {e}", exc_info=True)
            return False

    def run(self) -> bool:
        """
        运行爬虫主流程

        Returns:
            运行是否成功
        """
        try:
            self.logger.info("开始运行豆瓣电影爬虫...")

            # 1. 获取首页内容
            html_content = self.fetch_page(self.base_url)
            if not html_content:
                self.logger.error("获取首页内容失败")
                return False

            # 2. 解析电影数据
            self.movies = self.parse_homepage(html_content)

            if not self.movies:
                self.logger.warning("未解析到任何电影数据")
                return False

            # 3. 保存数据
            success = self.save_to_json()

            if success:
                self.logger.info(f"爬虫运行完成，共获取 {len(self.movies)} 部电影")
            else:
                self.logger.error("保存数据失败")

            return success

        except Exception as e:
            self.logger.error(f"爬虫运行过程中发生错误: {e}", exc_info=True)
            return False

    def print_summary(self) -> None:
        """打印爬取结果摘要"""
        if not self.movies:
            print("未获取到电影数据")
            return

        print(f"\n{'='*60}")
        print(f"豆瓣电影爬取结果摘要")
        print(f"{'='*60}")
        print(f"总电影数: {len(self.movies)}")
        print(f"有评分的电影: {sum(1 for m in self.movies if m.rating is not None)}")
        print(f"有海报的电影: {sum(1 for m in self.movies if m.poster_url)}")
        print(f"\n前5部电影:")

        for i, movie in enumerate(self.movies[:5], 1):
            rating_str = f"{movie.rating:.1f}" if movie.rating else "暂无评分"
            print(f"{i}. {movie.title} - 评分: {rating_str} - 导演: {movie.director or '未知'}")


def main() -> None:
    """主函数"""
    # 创建爬虫实例
    spider = DoubanMovieSpider()

    # 运行爬虫
    success = spider.run()

    # 打印结果摘要
    if success:
        spider.print_summary()
        print(f"\n数据已保存到 /workspace/douban_movies.json")
    else:
        print("爬虫运行失败，请查看日志文件获取详细信息")


if __name__ == "__main__":
    main()