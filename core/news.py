import json
import requests
import datetime
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus
from duckduckgo_search import DDGS
from config import OLLAMA_URL, RESPONDER_MODEL

class NewsManager:
    """Manages fetching and curating news for the Briefing dashboard."""

    def __init__(self):
        self.ddgs = DDGS()
        # Simple in-memory cache: {category: {"timestamp": dt, "data": []}}
        self.cache = {}
        self.cache_duration = datetime.timedelta(minutes=15)
        self.category_queries = {
            "Top Stories": "top news today",
            "Technology": "technology AI cybersecurity news today",
            "Markets": "business markets economy news today",
            "Science": "science health space breakthrough news today",
            "Culture": "culture entertainment media news today",
            "Trending": "trending topics social media today",
        }

    def get_briefing(self, status_callback=None, use_ai: bool = True) -> list:
        """
        Get a curated briefing.
        Fetches 'top' and 'technology' news, then asks AI to pick the best ones.
        """
        # 1. Check cache first
        if status_callback: status_callback("Checking local cache...")
        cache_key = "briefing_ai" if use_ai else "briefing_raw"
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        # 2. Fetch raw news
        raw_news = []
        try:
            if status_callback: status_callback("Scanning global headlines...")
            # Fetch generic top news
            for r in self.ddgs.news("top news", max_results=5):
                r['category'] = 'Top Stories'
                raw_news.append(r)
            
            if status_callback: status_callback("Retrieving technology sector updates...")
            # Fetch Tech news
            for r in self.ddgs.news("technology news", max_results=5):
                r['category'] = 'Technology'
                raw_news.append(r)
                
            # Fetch Science news
            for r in self.ddgs.news("science breakthrough", max_results=3):
                r['category'] = 'Science'
                raw_news.append(r)

        except Exception as e:
            print(f"Error fetching news from DDGS: {e}")
            # Rate limit or connection error - return empty to trigger fallback
            # In a production app, we might retry with backoff, but for now we fail gracefully.
            return []

        # 3. AI Curation
        curated_news = None
        if use_ai:
            if status_callback: status_callback("AI is reading and curating stories...")
            curated_news = self._curate_with_ai(raw_news)
        
        # 4. Fallback if AI fails: just return raw news formatted
        if not curated_news:
            curated_news = self._format_raw_fallback(raw_news)

        # 5. Save to cache
        self.cache[cache_key] = {
            "timestamp": datetime.datetime.now(),
            "data": curated_news
        }
        
        return curated_news

    def get_categorized_updates(
        self,
        status_callback=None,
        limit_per_category: int = 4,
    ) -> list:
        """Fetch current headlines and trends grouped for the command center."""
        cache_key = f"categorized_{limit_per_category}"
        if status_callback:
            status_callback("Checking local cache...")

        cached = self._get_from_cache(cache_key)
        if cached:
            return cached

        raw_news = []
        try:
            for category, query in self.category_queries.items():
                if status_callback:
                    status_callback(f"Fetching {category.lower()}...")

                for result in self.ddgs.news(query, max_results=limit_per_category):
                    result["category"] = category
                    raw_news.append(result)
        except Exception as e:
            print(f"Error fetching categorized updates from DDGS: {e}")
            raw_news = self._fetch_rss_fallback(status_callback, limit_per_category)

        if not raw_news:
            return []

        formatted = self._format_raw_fallback(raw_news, max_items=limit_per_category * 6)
        self.cache[cache_key] = {
            "timestamp": datetime.datetime.now(),
            "data": formatted,
        }
        return formatted

    def _fetch_rss_fallback(self, status_callback=None, limit_per_category: int = 4) -> list:
        """Use public RSS as a fallback when DDGS rate limits or fails."""
        raw_news = []
        headers = {"User-Agent": "PrincessLocalAssistant/1.0"}

        for category, query in self.category_queries.items():
            if status_callback:
                status_callback(f"Fetching {category.lower()} RSS...")

            url = (
                "https://news.google.com/rss/search?"
                f"q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
            )

            try:
                response = requests.get(url, headers=headers, timeout=20)
                response.raise_for_status()
                root = ET.fromstring(response.content)
                for item in root.findall(".//item")[:limit_per_category]:
                    raw_news.append({
                        "title": self._xml_text(item, "title"),
                        "source": self._xml_text(item, "source") or "Google News",
                        "date": self._xml_text(item, "pubDate"),
                        "category": category,
                        "url": self._xml_text(item, "link"),
                        "image": None,
                    })
            except Exception as exc:
                print(f"RSS fallback failed for {category}: {exc}")

        return raw_news

    def _xml_text(self, item, tag: str) -> str:
        found = item.find(tag)
        return found.text.strip() if found is not None and found.text else ""

    def _get_from_cache(self, key: str):
        if key in self.cache:
            entry = self.cache[key]
            if datetime.datetime.now() - entry["timestamp"] < self.cache_duration:
                return entry["data"]
        return None

    def _format_raw_fallback(self, raw_news, max_items: int = 8):
        """Fallback formatting if AI fails."""
        formatted = []
        seen_titles = set()
        
        for item in raw_news:
            if item['title'] in seen_titles:
                continue
            seen_titles.add(item['title'])
            
            formatted.append({
                "title": item.get('title'),
                "source": item.get('source'),
                "date": item.get('date'),
                "category": item.get('category', 'General'),
                "url": item.get('url'),
                "image": item.get('image') # DDGS might return 'image'
            })
        return formatted[:max_items]

    def _curate_with_ai(self, raw_news):
        """Send raw news to LLM to select and strictly format."""
        
        # Minify valid data for prompt
        # We only need title, source, category to make a decision
        news_input = [
            {"id": i, "title": n.get('title'), "source": n.get('source'), "category": n.get('category')} 
            for i, n in enumerate(raw_news)
        ]

        prompt = f"""
You are an expert News Editor.
Here is a list of raw news articles:
{json.dumps(news_input, indent=2)}

Task:
1. Select the 6 most important and diverse stories.
2. Rewrite the titles to be punchy and short (under 10 words).
3. Assign a category: 'Technology', 'Science', 'Markets', 'Culture', or 'Top Stories'.
4. Return ONLY a JSON array of objects.
   Format: [{{"id": <original_id>, "title": "<new_title>", "category": "<category>"}}]

Do NOT add any markdown or text. Just the JSON array.
"""
        
        try:
            response = requests.post(
                f"{OLLAMA_URL}/chat",
                json={
                    "model": RESPONDER_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "options": {"temperature": 0.3}
                },
                timeout=60
            )
            
            if response.status_code == 200:
                content = response.json()['message']['content']
                # Try to clean markdown code blocks if present
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].strip()
                
                selected = json.loads(content)
                
                # Merge back with original data (urls, images)
                final_list = []
                for s in selected:
                    original = raw_news[s['id']]
                    final_list.append({
                        "title": s['title'], # AI rewritten title
                        "source": original.get('source'),
                        "date": original.get('date'), # DDGS date is often "2 hours ago"
                        "category": s['category'], # AI Category
                        "url": original.get('url'),
                        "image": original.get('image'),
                        "body": original.get('body') # snippet
                    })
                return final_list
                
        except Exception as e:
            print(f"AI Curation failed: {e}")
            return None
        
        return None

news_manager = NewsManager()
