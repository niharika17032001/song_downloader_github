import requests
from lxml import html
from collections import deque
import json
import time
import os  # To check for file existence

# Import standard selenium webdriver
from selenium import webdriver
from selenium.webdriver.chrome.service import Service  # Required for specifying executable_path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException


def get_chrome_options():
    options = webdriver.ChromeOptions()  # Use standard ChromeOptions
    options.add_argument("--headless")  # Run in headless mode (no GUI)
    options.add_argument("--no-sandbox")  # Required for GitHub Actions' ubuntu-latest
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")  # Set a window size for headless
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    return options


def create_webdriver_instance(browser_type="chrome"):
    """Initializes and returns a Selenium WebDriver instance using standard Chrome."""
    if browser_type.lower() == "chrome":
        chrome_options = get_chrome_options()  # Get options for standard Chrome

        try:
            # On GitHub Actions, chromedriver is typically installed at /usr/bin/chromedriver
            # when using `apt-get install chromium-chromedriver`.
            service = Service(executable_path="/usr/bin/chromedriver")
            driver = webdriver.Chrome(service=service, options=chrome_options)
            return driver
        except WebDriverException as e:
            print(f"Error initializing ChromeDriver. Make sure chromedriver is installed and in PATH. Error: {e}")
            return None
    else:
        raise ValueError("Unsupported browser type. Only 'chrome' is configured.")


# --- Rest of your existing code (save_crawl_state, load_crawl_state, crawl_pagalgana_with_selenium) ---
# This part remains largely the same as the previous resumable version.

def save_crawl_state(to_visit_deque, visited_set, song_urls_list, state_filename="crawl_state.json",
                     output_json_file="pagalgana_song_pages.json"):
    """Saves the current state of the crawler to JSON files."""
    try:
        # Save song URLs (already in JSON format)
        with open(output_json_file, 'w', encoding='utf-8') as f:
            json.dump(song_urls_list, f, indent=4)

        # Save crawl state (to_visit and visited_urls)
        # Deque needs to be converted to list, set to list
        crawl_state_data = {
            "to_visit": list(to_visit_deque),
            "visited_urls": list(visited_set)
        }
        with open(state_filename, 'w', encoding='utf-8') as f:
            json.dump(crawl_state_data, f, indent=4)
        print(
            f"--- Crawl state saved. URLs to visit: {len(to_visit_deque)}, Visited: {len(visited_set)}, Songs found: {len(song_urls_list)} ---")
    except IOError as e:
        print(f"Error saving crawl state: {e}")
    except Exception as e:
        print(f"An unexpected error occurred while saving state: {e}")


def load_crawl_state(state_filename="crawl_state.json", output_json_file="pagalgana_song_pages.json"):
    """Loads previous crawl state if files exist."""
    to_visit_deque = deque()
    visited_set = set()
    song_urls_list = []

    if os.path.exists(output_json_file):
        try:
            with open(output_json_file, 'r', encoding='utf-8') as f:
                song_urls_list = json.load(f)
            print(f"Loaded {len(song_urls_list)} song URLs from '{output_json_file}'.")
        except json.JSONDecodeError:
            print(f"Warning: '{output_json_file}' is corrupted or empty. Starting fresh song list.")
            song_urls_list = []
        except Exception as e:
            print(f"Error loading '{output_json_file}': {e}")

    if os.path.exists(state_filename):
        try:
            with open(state_filename, 'r', encoding='utf-8') as f:
                crawl_state_data = json.load(f)
            to_visit_deque = deque(crawl_state_data.get("to_visit", []))
            visited_set = set(crawl_state_data.get("visited_urls", []))
            print(f"Loaded crawl state: {len(to_visit_deque)} URLs to visit, {len(visited_set)} visited.")
        except json.JSONDecodeError:
            print(f"Warning: '{state_filename}' is corrupted or empty. Starting fresh state.")
            to_visit_deque = deque()
            visited_set = set()
        except Exception as e:
            print(f"Error loading '{state_filename}': {e}")

    return to_visit_deque, visited_set, song_urls_list


def crawl_pagalgana_with_selenium(base_url="https://pagalgana.com/", output_json_file="pagalgana_song_pages.json",
                                  max_crawl_depth=3, state_filename="crawl_state.json", save_interval=20):
    """
    Crawls Pagalgana.com, handling 'Load More' buttons, and supports resuming.
    """
    driver = create_webdriver_instance()
    if not driver:
        print("Failed to initialize WebDriver. Exiting.")
        return

    # Load previous state
    to_visit, visited_urls, song_page_urls = load_crawl_state(state_filename, output_json_file)

    # If no state was loaded, initialize with base_url
    if not to_visit and not visited_urls:
        print("No previous crawl state found. Starting fresh.")
        to_visit.append((base_url, 0))
    else:
        print("Resuming crawl from previous state.")
        # Ensure the base_url is added if it wasn't processed and we're starting fresh
        if base_url not in visited_urls and (base_url, 0) not in to_visit and not song_page_urls:
            to_visit.appendleft((base_url, 0))  # Add to front if it's the very first page to process

    AUDIO_CONTAINER_XPATH = '//*[@id="audio-container"]'
    LOAD_MORE_BUTTON_XPATH = '//a[@class="button" and contains(@onclick, "loadMoreCategory")]'

    print(f"Starting/Resuming crawl with base: {base_url}, max depth: {max_crawl_depth}")
    print(
        f"Initial Queue size: {len(to_visit)}, Initial Visited size: {len(visited_urls)}, Initial Songs: {len(song_page_urls)}")

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
            print(f"  Current URL after load: {driver.current_url}")
            print("  --- HTML snippet (first 2000 chars) ---")
            print(driver.page_source[:2000])
            print("  --- End HTML snippet ---")

            # Check if it's a song page
            audio_container_elements = driver.find_elements(By.XPATH, AUDIO_CONTAINER_XPATH)
            if audio_container_elements:
                print(f"  --> FOUND AUDIO CONTAINER! This is a song page: {current_url}")
                song_page_urls.append(current_url)
                # No 'continue' here, as we still want to save state even if it's a song page
                # This ensures the song URL is saved periodically.
                # If you explicitly don't want to crawl links from song pages, add 'continue' back.
                # But for state saving, processing it here is better.

            # Handle "Load More" button if present (only if it's not a song page or still relevant)
            if not audio_container_elements:  # Only try to load more if it's not a song page
                load_more_found_and_clicked = False
                while True:
                    try:
                        load_more_button = WebDriverWait(driver, 15).until(  # Increased wait
                            EC.element_to_be_clickable((By.XPATH, LOAD_MORE_BUTTON_XPATH))
                        )

                        last_height = driver.execute_script("return document.body.scrollHeight")

                        print("  Clicking 'Load More' button...")
                        load_more_button.click()
                        load_more_found_and_clicked = True

                        new_height = last_height
                        scroll_attempts = 0
                        while new_height == last_height and scroll_attempts < 7:  # Max 7 attempts to wait for scroll
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
            print(f"  Found {len(links)} raw links on the page.")

            links_added_to_queue = 0
            for link in links:
                absolute_url = requests.compat.urljoin(current_url, link)
                # Ensure we don't add song pages back to the to_visit queue
                # if they've already been processed or are duplicates

                # Check for basic validity and domain
                if "pagalgana.com" in absolute_url and "#" not in absolute_url and "?" not in absolute_url:
                    # Exclude direct file links
                    if not (absolute_url.endswith(
                            ('.mp3', '.zip', '.rar', '.jpg', '.png', '.gif', '.pdf', '.txt', '.xml', '.css', '.js'))):
                        # Ensure not already visited or in queue
                        if absolute_url not in visited_urls and (absolute_url, current_depth + 1) not in to_visit:
                            # IMPORTANT: Don't add if it's already a discovered song page
                            if absolute_url not in song_page_urls:
                                to_visit.append((absolute_url, current_depth + 1))
                                links_added_to_queue += 1
            print(f"  Added {links_added_to_queue} new valid links to the queue from {current_url}.")

        except Exception as e:
            print(f"  An unexpected error occurred for {current_url}: {e}")
        finally:
            # Save state periodically
            if processed_count % save_interval == 0:
                print(f"--- Processed {processed_count} pages. Saving current state... ---")
                save_crawl_state(to_visit, visited_urls, song_page_urls, state_filename, output_json_file)

    driver.quit()  # Close the browser when done

    # Final save after loop finishes
    print("\n--- Crawl finished. Performing final save. ---")
    save_crawl_state(to_visit, visited_urls, song_page_urls, state_filename, output_json_file)
    print(f"\nCrawl complete. Total {len(song_page_urls)} song pages found and saved to '{output_json_file}'.")


# --- Run the crawler ---
if __name__ == "__main__":
    crawl_pagalgana_with_selenium(
        base_url="https://pagalgana.com/category/bollywood-mp3-songs.html",  # Start from a relevant category
        output_json_file="bollywood_song_pages.json",
        state_filename="bollywood_crawl_state.json",  # Separate state file for this crawl
        max_crawl_depth=3,  # Adjust depth as needed
        save_interval=10  # Save state every 10 pages processed
    )