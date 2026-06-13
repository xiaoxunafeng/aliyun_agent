#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
豆瓣电影首页爬虫
基于分析报告生成，提取以下数据：
1. 正在热映区域的电影信息
2. 一周口碑榜的电影排名
3. 最受欢迎的影评信息
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
    logger = logging.getLogger('douban_movie_spider')
    logger.setLevel(logging.INFO)
    
    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 创建文件处理器
    file_handler = logging.FileHandler('douban_spider.log', encoding='utf-8')
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
class MovieData:
    """电影数据结构"""
    title: str
    url: str
    rating: Optional[float] = None
    star_rating: Optional[int] = None
    release_year: Optional[int] = None
    duration: Optional[str] = None
    region: Optional[str] = None
    director: Optional[str] = None
    actors: Optional[List[str]] = None
    rater_count: Optional[int] = None
    poster_url: Optional[str] = None
    source_area: str = ""


@dataclass
class RankingData:
    """排行榜数据结构"""
    rank: str
    title: str
    url: str


@dataclass
class ReviewData:
    """影评数据结构"""
    review_title: str
    review_url: str
    movie_title: str
    movie_url: str
    author: Optional[str] = None
    rating_stars: Optional[str] = None


class DoubanMovieSpider:
    """豆瓣电影爬虫类"""
    
    def __init__(self):
        self.base_url = "https://movie.douban.com/"
        self.session = requests.Session()
        self.setup_headers()
        self.setup_session()
        
    def setup_headers(self):
        """设置请求头"""
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Referer': 'https://www.douban.com/',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
        
    def setup_session(self):
        """设置会话"""
        self.session.headers.update(self.headers)
        self.session.timeout = 30
        
    def random_delay(self, min_seconds=2, max_seconds=5):
        """随机延迟"""
        delay = random.uniform(min_seconds, max_seconds)
        logger.debug(f"等待 {delay:.2f} 秒...")
        time.sleep(delay)
        
    def fetch_page(self, url: str) -> Optional[str]:
        """获取页面内容"""
        try:
            logger.info(f"正在请求页面: {url}")
            self.random_delay()
            
            response = self.session.get(url, headers=self.headers)
            
            # 打印响应头，用于调试
            logger.info(f"Response Headers: Content-Type={response.headers.get('Content-Type')}, Content-Encoding={response.headers.get('Content-Encoding')}")

            # 检查是否被重定向到了登录页或验证页
            if 'accounts/login' in response.url:
                logger.error("❌ 警告: 被重定向到登录页面，IP可能受限")
                return None
                
            response.raise_for_status()
            
            # 检查编码
            if response.encoding is None:
                response.encoding = 'utf-8'
            
            # 保存调试文件
            try:
                with open('debug_page.html', 'w', encoding='utf-8') as f:
                    f.write(response.text)
                logger.info("已保存页面源码到 debug_page.html 用于排查")
            except Exception:
                pass

            # 简单的标题检查
            if "<title>" in response.text:
                title_start = response.text.find("<title>") + 7
                title_end = response.text.find("</title>")
                page_title = response.text[title_start:title_end].strip()
                logger.info(f"页面标题: {page_title}")
                if "登录" in page_title or "验证" in page_title or "禁止" in page_title:
                    logger.error(f"❌ 警告: 页面标题异常，可能触发了反爬虫: {page_title}")

            logger.info(f"页面请求成功，状态码: {response.status_code}")
            return response.text
            
        except requests.exceptions.RequestException as e:
            logger.error(f"请求页面失败: {e}")
            return None
        except Exception as e:
            logger.error(f"获取页面时发生未知错误: {e}")
            return None
    
    def parse_screening_movies(self, soup: BeautifulSoup) -> List[MovieData]:
        """解析正在热映电影区域"""
        logger.info("开始解析正在热映电影区域...")
        movies = []
        
        try:
            # 查找正在热映区域
            screening_section = soup.find('div', id='screening')
            if not screening_section:
                logger.warning("未找到正在热映区域")
                return movies
                
            # 查找所有电影项目
            movie_items = screening_section.find_all('li', class_='ui-slide-item')
            logger.info(f"找到 {len(movie_items)} 个正在热映的电影")
            
            for item in movie_items:
                try:
                    movie_data = self.extract_movie_data(item)
                    if movie_data:
                        movies.append(movie_data)
                except Exception as e:
                    logger.error(f"解析单个电影数据时出错: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"解析正在热映区域时出错: {e}")
            
        return movies
    
    def extract_movie_data(self, item) -> Optional[MovieData]:
        """从电影项目中提取数据"""
        try:
            # 从数据属性中提取信息
            data_title = item.get('data-title', '').strip()
            data_release = item.get('data-release', '').strip()
            data_rate = item.get('data-rate', '').strip()
            data_star = item.get('data-star', '').strip()
            data_duration = item.get('data-duration', '').strip()
            data_region = item.get('data-region', '').strip()
            data_director = item.get('data-director', '').strip()
            data_actors = item.get('data-actors', '').strip()
            data_rater = item.get('data-rater', '').strip()
            
            # 从DOM元素中提取信息
            title_elem = item.find('li', class_='title')
            title_link = title_elem.find('a') if title_elem else None
            title = title_link.get_text(strip=True) if title_link else data_title
            
            url = title_link.get('href', '') if title_link else ''
            
            # 提取评分
            rating_elem = item.find('span', class_='subject-rate')
            rating_text = rating_elem.get_text(strip=True) if rating_elem else data_rate
            
            # 提取海报
            poster_elem = item.find('li', class_='poster')
            poster_img = poster_elem.find('img') if poster_elem else None
            poster_url = poster_img.get('src', '') if poster_img else ''
            
            # 处理演员列表
            actors_list = []
            if data_actors:
                actors_list = [actor.strip() for actor in data_actors.split('/') if actor.strip()]
            
            # 转换数据类型
            rating = None
            if rating_text and rating_text != '暂无评分':
                try:
                    rating = float(rating_text)
                except ValueError:
                    logger.warning(f"无法转换评分: {rating_text}")
            
            star_rating = None
            if data_star:
                try:
                    star_rating = int(data_star)
                except ValueError:
                    pass
            
            release_year = None
            if data_release:
                try:
                    release_year = int(data_release)
                except ValueError:
                    pass
            
            rater_count = None
            if data_rater:
                try:
                    rater_count = int(data_rater)
                except ValueError:
                    pass
            
            movie = MovieData(
                title=title,
                url=url,
                rating=rating,
                star_rating=star_rating,
                release_year=release_year,
                duration=data_duration,
                region=data_region,
                director=data_director,
                actors=actors_list,
                rater_count=rater_count,
                poster_url=poster_url,
                source_area="正在热映"
            )
            
            logger.debug(f"提取电影数据: {title}")
            return movie
            
        except Exception as e:
            logger.error(f"提取电影数据时出错: {e}")
            return None
    
    def parse_weekly_ranking(self, soup: BeautifulSoup) -> List[RankingData]:
        """解析一周口碑榜"""
        logger.info("开始解析一周口碑榜...")
        rankings = []
        
        try:
            # 查找一周口碑榜区域
            billboard_section = soup.find('div', id='billboard')
            if not billboard_section:
                logger.warning("未找到一周口碑榜区域")
                return rankings
            
            # 查找表格行
            rows = billboard_section.find_all('tr')
            logger.info(f"找到 {len(rows)} 个排行榜项目")
            
            for row in rows:
                try:
                    # 跳过表头
                    if row.find('th'):
                        continue
                    
                    # 提取排名
                    rank_elem = row.find('td', class_='order')
                    rank = rank_elem.get_text(strip=True) if rank_elem else ''
                    
                    # 提取电影标题和链接
                    title_elem = row.find('td', class_='title')
                    title_link = title_elem.find('a') if title_elem else None
                    title = title_link.get_text(strip=True) if title_link else ''
                    url = title_link.get('href', '') if title_link else ''
                    
                    if title and url:
                        ranking = RankingData(
                            rank=rank,
                            title=title,
                            url=url
                        )
                        rankings.append(ranking)
                        logger.debug(f"提取排行榜数据: {rank} - {title}")
                        
                except Exception as e:
                    logger.error(f"解析单个排行榜项目时出错: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"解析一周口碑榜时出错: {e}")
            
        return rankings
    
    def parse_popular_reviews(self, soup: BeautifulSoup) -> List[ReviewData]:
        """解析最受欢迎的影评"""
        logger.info("开始解析最受欢迎的影评...")
        reviews = []
        
        try:
            # 查找影评区域
            reviews_section = soup.find('div', id='reviews')
            if not reviews_section:
                logger.warning("未找到影评区域")
                return reviews
            
            # 查找所有影评项目
            review_items = reviews_section.find_all('div', class_='review')
            logger.info(f"找到 {len(review_items)} 个影评")
            
            for item in review_items:
                try:
                    review_data = self.extract_review_data(item)
                    if review_data:
                        reviews.append(review_data)
                except Exception as e:
                    logger.error(f"解析单个影评时出错: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"解析影评区域时出错: {e}")
            
        return reviews
    
    def extract_review_data(self, item) -> Optional[ReviewData]:
        """从影评项目中提取数据"""
        try:
            # 提取影评标题和链接
            review_bd = item.find('div', class_='review-bd')
            review_title_elem = review_bd.find('h3').find('a') if review_bd else None
            review_title = review_title_elem.get_text(strip=True) if review_title_elem else ''
            review_url = review_title_elem.get('href', '') if review_title_elem else ''
            
            # 提取影评元数据
            review_meta = item.find('div', class_='review-meta')
            if review_meta:
                # 提取作者
                author_elem = review_meta.find('a')
                author = author_elem.get_text(strip=True) if author_elem else ''
                
                # 提取关联电影
                movie_links = review_meta.find_all('a')
                movie_link = movie_links[-1] if len(movie_links) > 1 else None
                movie_title = movie_link.get_text(strip=True) if movie_link else ''
                movie_url = movie_link.get('href', '') if movie_link else ''
                
                # 提取评分星星
                rating_elem = review_meta.find('span', class_='allstar')
                rating_stars = rating_elem.get('class', [''])[0] if rating_elem else ''
            else:
                author = ''
                movie_title = ''
                movie_url = ''
                rating_stars = ''
            
            if review_title and review_url:
                review = ReviewData(
                    review_title=review_title,
                    review_url=review_url,
                    movie_title=movie_title,
                    movie_url=movie_url,
                    author=author,
                    rating_stars=rating_stars
                )
                
                logger.debug(f"提取影评数据: {review_title}")
                return review
                
        except Exception as e:
            logger.error(f"提取影评数据时出错: {e}")
            
        return None
    
    def save_to_json(self, data: Dict[str, Any], filename: str = None):
        """保存数据为JSON格式"""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"douban_movie_data_{timestamp}.json"
        
        try:
            # 转换数据为可序列化的格式
            serializable_data = {
                'screening_movies': [asdict(movie) for movie in data.get('screening_movies', [])],
                'weekly_ranking': [asdict(ranking) for ranking in data.get('weekly_ranking', [])],
                'popular_reviews': [asdict(review) for review in data.get('popular_reviews', [])],
                'crawl_time': datetime.now().isoformat(),
                'source_url': self.base_url
            }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(serializable_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"数据已保存到: {filename}")
            return filename
            
        except Exception as e:
            logger.error(f"保存JSON文件时出错: {e}")
            return None
    
    def run(self):
        """运行爬虫"""
        logger.info("=" * 50)
        logger.info("开始爬取豆瓣电影首页数据")
        logger.info("=" * 50)
        
        # 获取页面内容
        html_content = self.fetch_page(self.base_url)
        if not html_content:
            logger.error("无法获取页面内容，爬虫终止")
            return None
        
        # 解析HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 提取各个区域的数据
        screening_movies = self.parse_screening_movies(soup)
        weekly_ranking = self.parse_weekly_ranking(soup)
        popular_reviews = self.parse_popular_reviews(soup)
        
        # 汇总数据
        all_data = {
            'screening_movies': screening_movies,
            'weekly_ranking': weekly_ranking,
            'popular_reviews': popular_reviews
        }
        
        # 输出统计信息
        logger.info("=" * 50)
        logger.info("爬取完成，数据统计:")
        logger.info(f"正在热映电影: {len(screening_movies)} 部")
        logger.info(f"一周口碑榜: {len(weekly_ranking)} 部")
        logger.info(f"最受欢迎影评: {len(popular_reviews)} 篇")
        logger.info("=" * 50)
        
        # 保存数据
        saved_file = self.save_to_json(all_data)
        
        # 显示部分数据示例
        if screening_movies:
            logger.info("正在热映电影示例:")
            for i, movie in enumerate(screening_movies[:3]):
                logger.info(f"  {i+1}. {movie.title} - 评分: {movie.rating}")
        
        if weekly_ranking:
            logger.info("一周口碑榜示例:")
            for ranking in weekly_ranking[:3]:
                logger.info(f"  {ranking.rank}. {ranking.title}")
        
        if popular_reviews:
            logger.info("最受欢迎影评示例:")
            for i, review in enumerate(popular_reviews[:3]):
                logger.info(f"  {i+1}. {review.review_title} - 电影: {review.movie_title}")
        
        return all_data


def main():
    """主函数"""
    try:
        # 创建爬虫实例
        spider = DoubanMovieSpider()
        
        # 运行爬虫
        data = spider.run()
        
        if data:
            logger.info("爬虫执行成功！")
            return 0
        else:
            logger.error("爬虫执行失败！")
            return 1
            
    except KeyboardInterrupt:
        logger.info("用户中断爬虫执行")
        return 130
    except Exception as e:
        logger.error(f"爬虫执行过程中发生未预期错误: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())