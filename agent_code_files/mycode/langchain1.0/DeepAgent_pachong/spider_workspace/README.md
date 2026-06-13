# 豆瓣电影爬虫 - 生产级实现

## 概述
基于豆瓣电影网站分析报告生成的面向对象、高可用、高鲁棒性的Python爬虫。

## 文件结构
- `/workspace/spider.py` - 主爬虫代码
- `/workspace/douban_movie_analysis_report.json` - 网站分析报告
- `/workspace/requirements.txt` - 依赖包列表
- `/workspace/test_spider.py` - 测试脚本

## 核心特性

### 1. OOP架构设计
- **类名**: `DoubanMovieSpider`
- **职责分离**:
  - `__init__`: 配置初始化
  - `fetch_page`: 网络请求
  - `parse_*`: 数据解析
  - `save_to_json`: 数据存储
  - `run()`: 流程调度

### 2. 高级数据提取策略
- **优先使用DOM属性**: 优先提取 `data-title`, `data-rate`, `data-director`, `data-actors` 等属性
- **防御性提取**: 所有 `find/find_all` 操作都包含判空逻辑
- **多区域解析**: 支持识别"正在热映"区域

### 3. 丰富的数据模型
- **@dataclass**: `MovieInfo` 数据模型
- **完整字段**:
  - `title`: str (电影标题)
  - `rating`: Optional[float] (评分)
  - `url`: str (电影链接)
  - `poster_url`: Optional[str] (海报链接)
  - `director`: Optional[str] (导演)
  - `actors`: Optional[str] (演员)
  - `duration`: Optional[str] (时长)
  - `region`: Optional[str] (地区)
  - `release_year`: Optional[str] (上映年份)
  - `rater_count`: Optional[int] (评分人数)
  - `star_level`: Optional[str] (星级)

### 4. 生产级健壮性
- **网络层**: `requests.Session()` 管理会话
- **User-Agent池**: 随机轮换User-Agent
- **Accept-Encoding**: 只包含 `gzip, deflate` (严禁'br')
- **容错层**: 关键解析循环内部有 `try-except`
- **日志层**: 完整的 `logging` 配置 (Console + File)

### 5. 标准化交付
- `main()` 函数和 `if __name__ == "__main__":` 入口
- `save_to_json()` 支持 `ensure_ascii=False` 和 `datetime` 序列化
- **随机延迟**: `random_delay()` 方法 (1-3秒)

## 使用方法

### 安装依赖
```bash
pip install -r requirements.txt
```

### 运行爬虫
```bash
python spider.py
```

### 输出文件
- `/workspace/douban_movies.json` - 电影数据
- `/workspace/douban_spider.log` - 日志文件

## 代码规范符合性检查

✅ **OOP架构**: 使用 `DoubanMovieSpider` 类  
✅ **数据模型**: 使用 `@dataclass` 定义 `MovieInfo`  
✅ **网络请求**: 使用 `requests.Session()`  
✅ **请求头规范**: `Accept-Encoding` 只包含 `gzip, deflate`  
✅ **随机延迟**: 实现 `random_delay()` 方法  
✅ **日志系统**: 配置完整的 `logging` 模块  
✅ **错误处理**: 关键解析逻辑使用 `try-except`  
✅ **防御性编程**: 检查元素是否为None  
✅ **数据保存**: 实现 `save_to_json()` 方法  
✅ **入口点**: 包含 `main()` 和 `if __name__ == "__main__":`

## 爬取目标
只爬取豆瓣电影首页的"正在热映"电影信息和链接，不爬取其他页面。

## 注意事项
1. 爬虫包含随机延迟，避免对目标网站造成过大压力
2. 使用User-Agent轮换，降低被屏蔽的风险
3. 所有网络请求都有超时设置和错误处理
4. 数据解析失败不会导致整个程序崩溃
5. 日志记录详细，便于问题排查