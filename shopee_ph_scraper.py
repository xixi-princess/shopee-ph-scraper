#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shopee Philippines 商品爬虫 + 数据分析脚本
功能：
1. 根据关键词搜索 Shopee 菲律宾站商品
2. 爬取商品列表数据（名称、价格、销量、评分等）
3. 保存为 CSV 文件
4. 进行基础数据分析并生成可视化图表

技术方案：
- 使用 requests 直接调用 Shopee 公开搜索 API
- 支持代理配置（解决国内IP访问问题）
- 站点：shopee.ph（菲律宾站）
- 支持分页爬取、自动重试、随机延迟

使用说明：
1. 安装依赖: pip install -r requirements.txt
2. 运行: python shopee_ph_scraper.py "phone" --pages 3
3. 使用代理: python shopee_ph_scraper.py "phone" --proxy http://user:pass@host:port
"""

import csv
import time
import random
import os
import argparse
from datetime import datetime
from urllib.parse import quote

import requests
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# ============ 配置区域 ============

# Shopee 菲律宾站配置
SHOPEE_PH_DOMAIN = "https://shopee.ph"
SEARCH_API_URL = "https://shopee.ph/api/v4/search/search_items"

# 默认参数
DEFAULT_MAX_PAGES = 3       # 默认爬取页数
DEFAULT_LIMIT = 60          # 每页商品数
DELAY_MIN = 2.0             # 最小请求延迟（秒）
DELAY_MAX = 5.0             # 最大请求延迟（秒）
MAX_RETRIES = 3             # 最大重试次数


# ============ 工具函数 ============

def random_delay():
    """随机延迟，防止请求过快被封"""
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def format_price(price_raw):
    """
    Shopee 价格字段是整数，需要除以 100000 得到真实价格
    """
    if price_raw is None:
        return 0.0
    return round(price_raw / 100000, 2)


def safe_get(d, *keys, default=None):
    """安全获取嵌套字典值"""
    for key in keys:
        if isinstance(d, dict) and key in d:
            d = d[key]
        else:
            return default
    return d


# ============ 核心爬虫类 ============

class ShopeePHScraper:
    """Shopee 菲律宾站商品爬虫（requests 版本）"""

    def __init__(self, keyword, max_pages=DEFAULT_MAX_PAGES, limit=DEFAULT_LIMIT,
                 output_dir="output", proxy=None):
        self.keyword = keyword
        self.max_pages = max_pages
        self.limit = limit
        self.output_dir = output_dir
        self.proxy = proxy
        self.products = []
        self.session = requests.Session()

        # 设置请求头（模拟 Safari 浏览器）
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/17.0 Safari/605.1.15"
            ),
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": f"https://shopee.ph/search?keyword={quote(keyword)}",
            "X-Requested-With": "XMLHttpRequest",
            "X-API-SOURCE": "pc",
        })

        # 设置代理
        if self.proxy:
            self.session.proxies = {
                "http": self.proxy,
                "https": self.proxy,
            }
            print(f"使用代理: {self.proxy}")

        # 创建输出目录
        os.makedirs(output_dir, exist_ok=True)

    def build_search_params(self, page):
        """构建搜索请求参数"""
        return {
            "by": "relevancy",
            "keyword": self.keyword,
            "limit": self.limit,
            "newest": (page - 1) * self.limit,
            "order": "desc",
            "page_type": "search",
            "scenario": "PAGE_GLOBAL_SEARCH",
            "version": "2",
        }

    def fetch_page(self, page):
        """
        获取单页搜索结果
        返回：items 列表 或 None（失败时）
        """
        params = self.build_search_params(page)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                print(f"  正在获取第 {page} 页... (尝试 {attempt}/{MAX_RETRIES})")
                random_delay()

                response = self.session.get(
                    SEARCH_API_URL,
                    params=params,
                    timeout=15
                )
                response.raise_for_status()
                data = response.json()

                if data.get("error"):
                    print(f"  API 返回错误: {data.get('error_msg', '未知错误')}")
                    return None

                items = data.get("items", [])
                print(f"  第 {page} 页获取成功，共 {len(items)} 条商品")
                return items

            except requests.exceptions.ProxyError as e:
                print(f"  代理错误: {e}")
                print("  请检查代理地址是否正确，或尝试不使用代理")
                return None
            except requests.exceptions.ConnectionError as e:
                print(f"  连接错误: {e}")
                print("  可能是网络问题，国内IP访问 shopee.ph 可能需要代理")
                if attempt < MAX_RETRIES:
                    wait = attempt * 3
                    print(f"  {wait} 秒后重试...")
                    time.sleep(wait)
                else:
                    return None
            except requests.exceptions.RequestException as e:
                print(f"  请求异常: {e}")
                if attempt < MAX_RETRIES:
                    wait = attempt * 2
                    print(f"  {wait} 秒后重试...")
                    time.sleep(wait)
                else:
                    print(f"  第 {page} 页获取失败，已达最大重试次数")
                    return None

    def parse_item(self, item):
        """解析单个商品数据"""
        item_basic = item.get("item_basic", {})
        if not item_basic:
            return None

        price = format_price(safe_get(item_basic, "price", default=0))
        price_before_discount = format_price(safe_get(item_basic, "price_before_discount", default=0))
        price_min = format_price(safe_get(item_basic, "price_min", default=0))
        price_max = format_price(safe_get(item_basic, "price_max", default=0))

        historical_sold = safe_get(item_basic, "historical_sold", default=0)
        sold = safe_get(item_basic, "sold", default=0)

        item_rating = safe_get(item_basic, "item_rating", default={})
        rating_star = safe_get(item_rating, "rating_star", default=0)
        rating_count = safe_get(item_rating, "rating_count", default=[0, 0, 0, 0, 0, 0])
        total_rating = sum(rating_count) if isinstance(rating_count, list) else 0

        shop_id = safe_get(item_basic, "shopid", default=0)
        shop_name = safe_get(item_basic, "shop_name", default="")

        item_id = safe_get(item_basic, "itemid", default=0)
        item_url = f"{SHOPEE_PH_DOMAIN}/product/{shop_id}/{item_id}" if shop_id and item_id else ""

        return {
            "item_id": item_id,
            "shop_id": shop_id,
            "shop_name": shop_name,
            "name": safe_get(item_basic, "name", default=""),
            "price": price,
            "price_before_discount": price_before_discount,
            "price_min": price_min,
            "price_max": price_max,
            "discount": round((1 - price / price_before_discount) * 100, 1) if price_before_discount > price > 0 else 0,
            "historical_sold": historical_sold,
            "sold": sold,
            "stock": safe_get(item_basic, "stock", default=0),
            "rating_star": round(rating_star, 2) if rating_star else 0,
            "rating_count": total_rating,
            "liked_count": safe_get(item_basic, "liked_count", default=0),
            "brand": safe_get(item_basic, "brand", default=""),
            "location": safe_get(item_basic, "shop_location", default=""),
            "is_official_shop": safe_get(item_basic, "is_official_shop", default=False),
            "is_preferred_plus_seller": safe_get(item_basic, "is_preferred_plus_seller", default=False),
            "item_url": item_url,
            "image": safe_get(item_basic, "image", default=""),
            "keyword": self.keyword,
            "crawl_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def run(self):
        """执行爬虫主流程"""
        print(f"\n{'='*60}")
        print(f"Shopee 菲律宾站商品爬虫")
        print(f"关键词: {self.keyword}")
        print(f"计划爬取: {self.max_pages} 页，每页 {self.limit} 条")
        if self.proxy:
            print(f"代理: 已启用")
        print(f"{'='*60}\n")

        for page in range(1, self.max_pages + 1):
            items = self.fetch_page(page)
            if items is None:
                print(f"  跳过第 {page} 页")
                continue

            if not items:
                print(f"  第 {page} 页无数据，结束爬取")
                break

            for item in items:
                parsed = self.parse_item(item)
                if parsed:
                    self.products.append(parsed)

            # 如果返回数量少于 limit，说明已到最后一页
            if len(items) < self.limit:
                print(f"  数据已到底，提前结束")
                break

        print(f"\n{'='*60}")
        print(f"爬取完成！共获取 {len(self.products)} 条商品数据")
        print(f"{'='*60}\n")
        return self.products

    def save_to_csv(self, filename=None):
        """保存数据到 CSV 文件"""
        if not self.products:
            print("没有数据可保存")
            return None

        if filename is None:
            safe_keyword = "".join(c if c.isalnum() else "_" for c in self.keyword)
            filename = f"{safe_keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        filepath = os.path.join(self.output_dir, filename)

        fieldnames = [
            "item_id", "shop_id", "shop_name", "name", "price", "price_before_discount",
            "price_min", "price_max", "discount", "historical_sold", "sold", "stock",
            "rating_star", "rating_count", "liked_count", "brand", "location",
            "is_official_shop", "is_preferred_plus_seller", "item_url", "image",
            "keyword", "crawl_time",
        ]

        with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.products)

        print(f"数据已保存到: {filepath}")
        return filepath


# ============ 数据分析模块 ============

class ShopeeDataAnalyzer:
    """Shopee 商品数据分析器"""

    def __init__(self, csv_path, output_dir="output"):
        self.csv_path = csv_path
        self.output_dir = output_dir
        self.df = None
        os.makedirs(output_dir, exist_ok=True)

    def load_data(self):
        """加载 CSV 数据"""
        self.df = pd.read_csv(self.csv_path, encoding="utf-8-sig")
        print(f"\n加载数据完成，共 {len(self.df)} 条记录")
        return self.df

    def basic_stats(self):
        """基础统计信息"""
        print("\n" + "="*60)
        print("基础统计信息")
        print("="*60)

        print(f"\n总商品数: {len(self.df)}")
        print(f"店铺数: {self.df['shop_id'].nunique()}")
        print(f"品牌数: {self.df['brand'].nunique()}")

        print(f"\n价格统计 (PHP):")
        price_stats = self.df["price"].describe()
        print(f"  平均价格: ₱{price_stats['mean']:.2f}")
        print(f"  最低价格: ₱{price_stats['min']:.2f}")
        print(f"  最高价格: ₱{price_stats['max']:.2f}")
        print(f"  中位数:   ₱{price_stats['50%']:.2f}")

        print(f"\n销量统计:")
        sold_stats = self.df["historical_sold"].describe()
        print(f"  平均销量: {sold_stats['mean']:.0f}")
        print(f"  最高销量: {sold_stats['max']:.0f}")

        print(f"\n评分统计:")
        rating_stats = self.df["rating_star"].describe()
        print(f"  平均评分: {rating_stats['mean']:.2f}")
        print(f"  最高评分: {rating_stats['max']:.2f}")

        print(f"\n官方店铺占比: {self.df['is_official_shop'].mean()*100:.1f}%")
        print(f"优选卖家占比: {self.df['is_preferred_plus_seller'].mean()*100:.1f}%")

    def generate_charts(self):
        """生成数据分析图表"""
        print("\n正在生成分析图表...")

        plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        sns.set_style("whitegrid")

        safe_keyword = os.path.basename(self.csv_path).replace(".csv", "")

        # 1. 综合分析图
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle(f"Shopee Philippines - '{safe_keyword}' 商品数据分析", fontsize=16, fontweight="bold")

        # 价格分布
        ax1 = axes[0, 0]
        price_data = self.df[self.df["price"] > 0]["price"]
        ax1.hist(price_data, bins=30, color="skyblue", edgecolor="black", alpha=0.7)
        ax1.set_title("Price Distribution (PHP)")
        ax1.set_xlabel("Price (PHP)")
        ax1.set_ylabel("Count")
        ax1.axvline(price_data.median(), color="red", linestyle="--", label=f"Median: ₱{price_data.median():.0f}")
        ax1.legend()

        # 销量 TOP 10
        ax2 = axes[0, 1]
        top_sold = self.df.nlargest(10, "historical_sold")[["name", "historical_sold"]]
        top_sold["name_short"] = top_sold["name"].apply(lambda x: x[:30] + "..." if len(x) > 30 else x)
        ax2.barh(top_sold["name_short"], top_sold["historical_sold"], color="lightcoral")
        ax2.set_title("Top 10 Best-Selling Products")
        ax2.set_xlabel("Historical Sold")
        ax2.invert_yaxis()

        # 评分分布
        ax3 = axes[1, 0]
        rating_data = self.df[self.df["rating_star"] > 0]["rating_star"]
        ax3.hist(rating_data, bins=20, color="lightgreen", edgecolor="black", alpha=0.7)
        ax3.set_title("Rating Distribution")
        ax3.set_xlabel("Rating Star")
        ax3.set_ylabel("Count")
        ax3.axvline(rating_data.mean(), color="red", linestyle="--", label=f"Mean: {rating_data.mean():.2f}")
        ax3.legend()

        # 价格 vs 销量 散点图
        ax4 = axes[1, 1]
        scatter_data = self.df[(self.df["price"] > 0) & (self.df["historical_sold"] > 0)]
        ax4.scatter(scatter_data["price"], scatter_data["historical_sold"], alpha=0.5, color="purple")
        ax4.set_title("Price vs Sales Volume")
        ax4.set_xlabel("Price (PHP)")
        ax4.set_ylabel("Historical Sold")
        ax4.set_yscale("log")

        plt.tight_layout(rect=[0, 0, 1, 0.95])
        chart_path = os.path.join(self.output_dir, f"{safe_keyword}_analysis.png")
        plt.savefig(chart_path, dpi=150, bbox_inches="tight")
        print(f"图表已保存到: {chart_path}")
        plt.close()

        # 2. 品牌分布图
        brand_counts = self.df[self.df["brand"] != ""]["brand"].value_counts().head(10)
        if len(brand_counts) >= 3:
            fig, ax = plt.subplots(figsize=(10, 6))
            brand_counts.plot(kind="bar", ax=ax, color="teal", alpha=0.8)
            ax.set_title("Top 10 Brands by Product Count")
            ax.set_xlabel("Brand")
            ax.set_ylabel("Count")
            plt.xticks(rotation=45, ha="right")
            plt.tight_layout()
            brand_chart_path = os.path.join(self.output_dir, f"{safe_keyword}_brands.png")
            plt.savefig(brand_chart_path, dpi=150, bbox_inches="tight")
            print(f"品牌分布图已保存到: {brand_chart_path}")
            plt.close()

    def export_summary(self):
        """导出分析摘要到文本文件"""
        safe_keyword = os.path.basename(self.csv_path).replace(".csv", "")
        summary_path = os.path.join(self.output_dir, f"{safe_keyword}_summary.txt")

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"Shopee Philippines 商品数据分析报告\n")
            f.write(f"关键词: {safe_keyword}\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("="*60 + "\n\n")

            f.write(f"总商品数: {len(self.df)}\n")
            f.write(f"店铺数: {self.df['shop_id'].nunique()}\n")
            f.write(f"品牌数: {self.df['brand'].nunique()}\n\n")

            f.write("价格统计 (PHP):\n")
            price_stats = self.df["price"].describe()
            f.write(f"  平均价格: ₱{price_stats['mean']:.2f}\n")
            f.write(f"  最低价格: ₱{price_stats['min']:.2f}\n")
            f.write(f"  最高价格: ₱{price_stats['max']:.2f}\n")
            f.write(f"  中位数:   ₱{price_stats['50%']:.2f}\n\n")

            f.write("销量 TOP 10:\n")
            top10 = self.df.nlargest(10, "historical_sold")[["name", "price", "historical_sold", "rating_star"]]
            for idx, row in top10.iterrows():
                f.write(f"  {row['name'][:50]}\n")
                f.write(f"    价格: ₱{row['price']:.2f} | 销量: {row['historical_sold']} | 评分: {row['rating_star']}\n\n")

        print(f"分析摘要已保存到: {summary_path}")
        return summary_path

    def run_analysis(self):
        """执行完整分析流程"""
        self.load_data()
        self.basic_stats()
        self.generate_charts()
        self.export_summary()
        print("\n分析完成！")


# ============ 命令行入口 ============

def main():
    parser = argparse.ArgumentParser(description="Shopee Philippines 商品爬虫与数据分析工具")
    parser.add_argument("keyword", help="搜索关键词（如：phone, shoes, bag 等）")
    parser.add_argument("--pages", type=int, default=DEFAULT_MAX_PAGES, help=f"爬取页数（默认 {DEFAULT_MAX_PAGES}）")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"每页商品数（默认 {DEFAULT_LIMIT}）")
    parser.add_argument("--output", default="output", help="输出目录（默认 output）")
    parser.add_argument("--no-analysis", action="store_true", help="跳过数据分析，仅爬取数据")
    parser.add_argument("--proxy", default=None, help="代理服务器地址（如：http://user:pass@host:port）")

    args = parser.parse_args()

    # 1. 执行爬虫
    scraper = ShopeePHScraper(
        keyword=args.keyword,
        max_pages=args.pages,
        limit=args.limit,
        output_dir=args.output,
        proxy=args.proxy,
    )
    scraper.run()

    if not scraper.products:
        print("\n未获取到任何数据，可能的原因：")
        print("1. 网络连接问题（国内IP访问 shopee.ph 可能需要代理）")
        print("2. 关键词无搜索结果")
        print("3. 被反爬机制拦截")
        print("\n建议：")
        print("- 尝试使用代理: python shopee_ph_scraper.py phone --proxy http://127.0.0.1:7890")
        print("- 减少爬取页数: python shopee_ph_scraper.py phone --pages 1")
        return

    # 2. 保存数据
    csv_path = scraper.save_to_csv()

    # 3. 数据分析
    if not args.no_analysis and csv_path:
        analyzer = ShopeeDataAnalyzer(csv_path, output_dir=args.output)
        analyzer.run_analysis()


if __name__ == "__main__":
    main()
