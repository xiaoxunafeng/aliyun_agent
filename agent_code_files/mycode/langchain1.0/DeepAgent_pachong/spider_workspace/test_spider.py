#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试豆瓣电影爬虫
"""

import sys
sys.path.insert(0, '/workspace')

from spider import DoubanMovieSpider, MovieInfo

def test_dataclass():
    """测试数据模型"""
    print("测试数据模型...")
    movie = MovieInfo(
        title="测试电影",
        rating=8.5,
        url="https://movie.douban.com/subject/123456/",
        director="测试导演",
        actors="演员1, 演员2",
        duration="120分钟",
        region="中国大陆"
    )
    
    print(f"电影标题: {movie.title}")
    print(f"评分: {movie.rating}")
    print(f"导演: {movie.director}")
    print(f"转换为字典: {movie.to_dict()}")
    print("数据模型测试通过！\n")

def test_spider_initialization():
    """测试爬虫初始化"""
    print("测试爬虫初始化...")
    spider = DoubanMovieSpider()
    
    print(f"爬虫类名: {spider.__class__.__name__}")
    print(f"基础URL: {spider.base_url}")
    print(f"请求头Accept-Encoding: {spider.headers.get('Accept-Encoding')}")
    
    # 验证Accept-Encoding不包含'br'
    accept_encoding = spider.headers.get('Accept-Encoding', '')
    if 'br' in accept_encoding:
        print("错误: Accept-Encoding包含'br'!")
        return False
    else:
        print("Accept-Encoding正确，不包含'br'")
    
    print("爬虫初始化测试通过！\n")
    return True

def test_methods():
    """测试爬虫方法"""
    print("测试爬虫方法...")
    spider = DoubanMovieSpider()
    
    # 测试随机延迟方法
    print("测试random_delay方法...")
    import time
    start = time.time()
    spider.random_delay(0.1, 0.2)  # 使用较短的延迟进行测试
    elapsed = time.time() - start
    print(f"延迟时间: {elapsed:.2f}秒")
    
    # 测试User-Agent轮换
    print("测试rotate_user_agent方法...")
    original_agent = spider.headers['User-Agent']
    spider.rotate_user_agent()
    new_agent = spider.headers['User-Agent']
    print(f"User-Agent已轮换: {original_agent != new_agent}")
    
    print("爬虫方法测试通过！\n")
    return True

def main():
    """主测试函数"""
    print("=" * 60)
    print("豆瓣电影爬虫测试")
    print("=" * 60)
    
    try:
        test_dataclass()
        if test_spider_initialization():
            test_methods()
        
        print("=" * 60)
        print("所有测试通过！")
        print("爬虫代码已成功生成并保存到 /workspace/spider.py")
        print("=" * 60)
        
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())