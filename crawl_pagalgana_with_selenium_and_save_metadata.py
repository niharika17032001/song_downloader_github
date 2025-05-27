import requests
from lxml import html
from collections import deque
import json
import time
import os
import re  # For regex in extract_audio_url
from bs4 import BeautifulSoup  # For tbody_to_json

# Selenium imports (ensure you've chosen either standard or undetected_chromedriver)
# --- OPTION A: Standard Selenium (if Cloudflare issues are resolved or not present) ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
# --- OR OPTION B: undetected_chromedriver (recommended for Cloudflare) ---
# import undetected_chromedriver as uc


from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException


# --- Helper functions for metadata extraction (from your provided script) ---
def fetch_html_tree_requests(url: str) -> tuple:
    """Fetches HTML using requests (not Selenium) and returns lxml tree and raw HTML."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    try:
        response = requests.get(url, headers=headers, timeout=10)  # Added timeout
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        return html.fromstring(response.content), response.text
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url} with requests: {e}")
        return None, None


def extract_tbody_html(tree: html.HtmlElement, xpath: str = "/html/body/div[3]/table/tbody") -> str:
    """Extracts the tbody HTML string from an lxml tree."""
    result = tree.xpath(xpath)
    if not result:
        # print(f"Warning: Element not found at XPath: {xpath}")
        return None  # Return None if not found, allowing graceful handling
    return html.tostring(result[0], encoding='unicode')


def extract_thumbnail(tree: html.HtmlElement) -> str:
    """Extracts the thumbnail URL from JSON-LD script tags."""
    scripts = tree.xpath("//script[@type='application/ld+json']/text()")
    for script in scripts:
        try:
            json_data = json.loads(script.strip())
            if isinstance(json_data, dict) and "image" in json_data:
                return json_data["image"]
        except json.JSONDecodeError:
            continue
    return None


def extract_audio_url(html_text: str) -> str:
    """Extracts the MP3 audio URL using regex from raw HTML."""
    match = re.search(r'new Audio\(["\'](https://[^"\']+\.mp3)["\']\)', html_text)
    return match.group(1) if match else None


def tbody_to_json(html_tbody: str) -> dict:
    """Parses tbody HTML using BeautifulSoup and converts to a dictionary."""
    if not html_tbody:
        return {}
    soup = BeautifulSoup(html_tbody, "html.parser")
    data = {}

    for tr in soup.find_all("tr", class_="tr"):
        tds = tr.find_all("td")
        if len(tds) < 2:
            continue

        key = tds[0].get_text(strip=True).rstrip(":")
        value_cell = tds[1]

        if key == "Rating":
            stars = value_cell.find_all("span")
            if stars:
                stars_str = ''.join(star.get_text(strip=True) for star in stars)
                data[key] = {
                    "stars": stars_str,
                    "out_of": 5,
                    "value": stars_str.count("★") + 0.5 * stars_str.count("☆")
                }
            continue

        value = value_cell.get_text(" ", strip=True)
        data[key] = value

    return data


def extract_song_metadata(url: str) -> dict:
    """Fetches a song page and extracts all relevant metadata."""
    print(f"  Attempting to extract metadata from: {url}")
    tree, html_text = fetch_html_tree_requests(url)
    if tree is None:  # If requests failed to fetch
        return {"URL": url, "error": "Failed to fetch page with requests"}

    metadata = {"URL": url}  # Always include the URL

    try:
        tbody_html = extract_tbody_html(tree)
        if tbody_html:
            metadata.update(tbody_to_json(tbody_html))
        else:
            metadata["tbody_data_present"] = False

        thumbnail_url = extract_thumbnail(tree)
        if thumbnail_url:
            metadata["Thumbnail"] = thumbnail_url

        audio_url = extract_audio_url(html_text)
        if audio_url:
            metadata["Play Online"] = audio_url
        else:
            metadata["Play Online"] = None  # Explicitly mark if not found

    except Exception as e:
        metadata["error_extracting_metadata"] = str(e)
        print(f"  Error extracting metadata for {url}: {e}")

    return metadata


# --- Selenium setup (choose one: standard or undetected_chromedriver) ---

# OPTION A: Standard Selenium (Use this if you reverted from UC)
def get_chrome_options():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    return options


def create_webdriver_instance(browser_type="chrome"):
    if browser_type.lower() == "chrome":
        chrome_options = get_chrome_options()
        try:
            # service = Service(executable_path="/usr/bin/chromedriver")
            driver = webdriver.Chrome(options=chrome_options)
            return driver
        except WebDriverException as e:
            print(f"Error initializing ChromeDriver. Error: {e}")
            return None
    else:
        raise ValueError("Unsupported browser type.")


# OPTION B: undetected_chromedriver (Uncomment and use this if you want to go back to UC)
# import undetected_chromedriver as uc
# def get_chrome_options():
#     options = uc.ChromeOptions()
#     options.add_argument("--headless")
#     options.add_argument("--no-sandbox")
#     options.add_argument("--disable-gpu")
#     options.add_argument("--disable-dev-shm-usage")
#     options.add_argument("--window-size=1920,1080")
#     return options

# def create_webdriver_instance(browser_type="chrome"):
#     if browser_type.lower() == "chrome":
#         chrome_options = get_chrome_options()
#         try:
#             driver = uc.Chrome(options=chrome_options)
#             return driver
#         except WebDriverException as e:
#             print(f"Error initializing undetected_chromedriver. Error: {e}")
#             return None
#     else:
#         raise ValueError("Unsupported browser type.")


# --- Resumable Crawler Logic (remains largely the same) ---

def save_crawl_state(to_visit_deque, visited_set, song_urls_list, metadata_list, state_filename="crawl_state.json",
                     song_pages_json_file="pagalgana_song_pages.json",
                     metadata_json_file="pagalgana_song_metadata.json"):
    """Saves the current state of the crawler and extracted metadata to JSON files."""
    try:
        # Save identified song page URLs
        with open(song_pages_json_file, 'w', encoding='utf-8') as f:
            json.dump(song_urls_list, f, indent=4)

        # Save extracted song metadata
        with open(metadata_json_file, 'w', encoding='utf-8') as f:
            json.dump(metadata_list, f, indent=4, ensure_ascii=False)  # ensure_ascii for proper chars like '★'

        # Save crawl state (to_visit and visited_urls)
        crawl_state_data = {
            "to_visit": list(to_visit_deque),
            "visited_urls": list(visited_set)
        }
        with open(state_filename, 'w', encoding='utf-8') as f:
            json.dump(crawl_state_data, f, indent=4)
        print(
            f"--- Crawl state saved. URLs to visit: {len(to_visit_deque)}, Visited: {len(visited_set)}, Song pages found: {len(song_urls_list)}, Metadata entries: {len(metadata_list)} ---")
    except IOError as e:
        print(f"Error saving crawl state: {e}")
    except Exception as e:
        print(f"An unexpected error occurred while saving state: {e}")


def load_crawl_state(state_filename="crawl_state.json", song_pages_json_file="pagalgana_song_pages.json",
                     metadata_json_file="pagalgana_song_metadata.json"):
    """Loads previous crawl state if files exist."""
    to_visit_deque = deque()
    visited_set = set()
    song_urls_list = []
    metadata_list = []

    if os.path.exists(song_pages_json_file):
        try:
            with open(song_pages_json_file, 'r', encoding='utf-8') as f:
                song_urls_list = json.load(f)
            print(f"Loaded {len(song_urls_list)} song URLs from '{song_pages_json_file}'.")
        except json.JSONDecodeError:
            print(f"Warning: '{song_pages_json_file}' corrupted or empty. Starting fresh song list.")
        except Exception as e:
            print(f"Error loading '{song_pages_json_file}': {e}")

    if os.path.exists(metadata_json_file):
        try:
            with open(metadata_json_file, 'r', encoding='utf-8') as f:
                metadata_list = json.load(f)
            print(f"Loaded {len(metadata_list)} metadata entries from '{metadata_json_file}'.")
        except json.JSONDecodeError:
            print(f"Warning: '{metadata_json_file}' corrupted or empty. Starting fresh metadata list.")
        except Exception as e:
            print(f"Error loading '{metadata_json_file}': {e}")

    if os.path.exists(state_filename):
        try:
            with open(state_filename, 'r', encoding='utf-8') as f:
                crawl_state_data = json.load(f)
            to_visit_deque = deque(crawl_state_data.get("to_visit", []))
            visited_set = set(crawl_state_data.get("visited_urls", []))
            print(f"Loaded crawl state: {len(to_visit_deque)} URLs to visit, {len(visited_set)} visited.")
        except json.JSONDecodeError:
            print(f"Warning: '{state_filename}' corrupted or empty. Starting fresh state.")
        except Exception as e:
            print(f"Error loading '{state_filename}': {e}")

    return to_visit_deque, visited_set, song_urls_list, metadata_list


def crawl_pagalgana_with_selenium(base_url="https://pagalgana.com/", song_pages_json_file="pagalgana_song_pages.json",
                                  metadata_json_file="pagalgana_song_metadata.json", max_crawl_depth=3,
                                  state_filename="crawl_state.json", save_interval=20):
    """
    Crawls Pagalgana.com, handling 'Load More' buttons, and supports resuming.
    Also extracts and saves detailed metadata for song pages.
    """
    driver = create_webdriver_instance()
    if not driver:
        print("Failed to initialize WebDriver. Exiting.")
        return

    # Load previous state
    to_visit, visited_urls, song_page_urls, song_metadata_list = load_crawl_state(state_filename, song_pages_json_file,
                                                                                  metadata_json_file)

    # Initialize with base_url if no previous state was loaded
    if not to_visit and not visited_urls:
        print("No previous crawl state found. Starting fresh.")
        to_visit.append((base_url, 0))
    else:
        print("Resuming crawl from previous state.")
        if base_url not in visited_urls and (base_url, 0) not in to_visit:
            # Add base_url to front if it's not been visited or processed, good for clean start or restart
            to_visit.appendleft((base_url, 0))

            # Create a set of URLs for which we already have metadata to avoid re-extracting
    processed_metadata_urls = {entry.get("URL") for entry in song_metadata_list if "URL" in entry}

    AUDIO_CONTAINER_XPATH = '//*[@id="audio-container"]'
    LOAD_MORE_BUTTON_XPATH = '//a[@class="button" and contains(@onclick, "loadMoreCategory")]'

    print(f"Starting/Resuming crawl with base: {base_url}, max depth: {max_crawl_depth}")
    print(
        f"Initial Queue size: {len(to_visit)}, Initial Visited size: {len(visited_urls)}, Song page URLs: {len(song_page_urls)}, Metadata entries: {len(song_metadata_list)}")

    processed_count = 0
    while to_visit:
        current_url, current_depth = to_visit.popleft()

        if current_url in visited_urls:
            continue

        if current_depth > max_crawl_depth:
            print(f"Skipping {current_url} - max depth reached ({max_crawl_depth})")
            continue

        print(f"\n--- Visiting ({current_depth}): {current_url} ---")
        visited_urls.add(current_url)
        processed_count += 1

        try:
            driver.get(current_url)
            time.sleep(3)  # Give page more time to load and execute JS

            # Debugging: Print a snippet of the page source
            print(f"  Page title: {driver.title}")
            # print(f"  Current URL after load: {driver.current_url}")
            # print("  --- HTML snippet (first 2000 chars) ---")
            # print(driver.page_source[:2000])
            # print("  --- End HTML snippet ---")

            # Check if it's a song page
            audio_container_elements = driver.find_elements(By.XPATH, AUDIO_CONTAINER_XPATH)
            if audio_container_elements:
                print(f"  --> FOUND AUDIO CONTAINER! This is a song page: {current_url}")
                if current_url not in song_page_urls:
                    song_page_urls.append(current_url)

                # --- EXTRACT METADATA FOR THIS SONG PAGE ---
                if current_url not in processed_metadata_urls:  # Only extract if not already done
                    metadata = extract_song_metadata(current_url)  # Use the requests-based function
                    song_metadata_list.append(metadata)
                    processed_metadata_urls.add(current_url)  # Mark as processed
                    print(f"  --> Extracted metadata for song page: {current_url}")
                else:
                    print(f"  --> Metadata already extracted for {current_url}. Skipping.")
                # No 'continue' here, we still want to process links from this page if relevant

            # Handle "Load More" button if present (only if it's not a song page or still relevant)
            # This logic allows categories to expand, regardless if the page eventually holds song data
            load_more_found_and_clicked = False
            while True:
                try:
                    load_more_button = WebDriverWait(driver, 15).until(
                        EC.element_to_be_clickable((By.XPATH, LOAD_MORE_BUTTON_XPATH))
                    )

                    last_height = driver.execute_script("return document.body.scrollHeight")

                    print("  Clicking 'Load More' button...")
                    load_more_button.click()
                    load_more_found_and_clicked = True

                    new_height = last_height
                    scroll_attempts = 0
                    while new_height == last_height and scroll_attempts < 7:
                        time.sleep(2)
                        new_height = driver.execute_script("return document.body.scrollHeight")
                        scroll_attempts += 1

                    if new_height == last_height:
                        print("  No more content loaded after click, or button disappeared.")
                        break

                except (NoSuchElementException, TimeoutException):
                    if not load_more_found_and_clicked:
                        print("  'Load More' button not found or not clickable.")
                    else:
                        print("  'Load More' button no longer present (all content likely loaded).")
                    break
                except Exception as e:
                    print(f"  Error clicking 'Load More': {e}")
                    break

            # After all content is loaded, parse the HTML
            tree = html.fromstring(driver.page_source)

            # Extract nested links from the fully loaded page
            links = tree.xpath('//a/@href')
            # print(f"  Found {len(links)} raw links on the page.")

            links_added_to_queue = 0
            for link in links:
                absolute_url = requests.compat.urljoin(current_url, link)

                if "pagalgana.com" in absolute_url and "#" not in absolute_url and "?" not in absolute_url:
                    if not (absolute_url.endswith(
                            ('.mp3', '.zip', '.rar', '.jpg', '.png', '.gif', '.pdf', '.txt', '.xml', '.css', '.js'))):
                        if absolute_url not in visited_urls and (absolute_url, current_depth + 1) not in to_visit:
                            if absolute_url not in song_page_urls:  # Don't re-add if already identified as a song page
                                to_visit.append((absolute_url, current_depth + 1))
                                links_added_to_queue += 1
            # print(f"  Added {links_added_to_queue} new valid links to the queue from {current_url}.")

        except Exception as e:
            print(f"  An unexpected error occurred for {current_url}: {e}")
        finally:
            # Save state periodically
            if processed_count % save_interval == 0:
                print(f"--- Processed {processed_count} pages. Saving current state... ---")
                save_crawl_state(to_visit, visited_urls, song_page_urls, song_metadata_list, state_filename,
                                 song_pages_json_file, metadata_json_file)

    driver.quit()  # Close the browser when done

    # Final save after loop finishes
    print("\n--- Crawl finished. Performing final save. ---")
    save_crawl_state(to_visit, visited_urls, song_page_urls, song_metadata_list, state_filename, song_pages_json_file,
                     metadata_json_file)
    print(f"\nCrawl complete. Total {len(song_page_urls)} song pages found and saved to '{song_pages_json_file}'.")
    print(f"Total {len(song_metadata_list)} song metadata entries saved to '{metadata_json_file}'.")


# --- Example usage ---
if __name__ == "__main__":
    crawl_pagalgana_with_selenium(
        base_url="https://pagalgana.com",
        song_pages_json_file="bollywood_song_pages.json",  # File for list of song page URLs
        metadata_json_file="bollywood_song_metadata.json",  # File for detailed metadata
        state_filename="bollywood_crawl_state.json",
        max_crawl_depth=10,
        save_interval=10
    )