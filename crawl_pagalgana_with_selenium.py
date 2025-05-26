import requests
from lxml import html
from collections import deque
import json
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException


def create_webdriver_instance(browser_type="chrome"):
    """Initializes and returns a Selenium WebDriver instance."""
    if browser_type.lower() == "chrome":
        options = webdriver.ChromeOptions()
        # options.add_argument("--headless")  # Run in headless mode (no GUI)
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # Add a user-agent to mimic a real browser
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        # Optional: Disable images for faster loading (though it might affect some JS)
        # prefs = {"profile.managed_default_content_settings.images": 2}
        # options.add_experimental_option("prefs", prefs)

        try:
            driver = webdriver.Chrome(options=options)
            return driver
        except WebDriverException as e:
            print(
                f"Error initializing ChromeDriver. Make sure chromedriver is in PATH and matches your Chrome version. Error: {e}")
            return None
    elif browser_type.lower() == "firefox":
        options = webdriver.FirefoxOptions()
        options.add_argument("--headless")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0")
        try:
            driver = webdriver.Firefox(options=options)
            return driver
        except WebDriverException as e:
            print(
                f"Error initializing GeckoDriver. Make sure geckodriver is in PATH and matches your Firefox version. Error: {e}")
            return None
    else:
        raise ValueError("Unsupported browser type. Choose 'chrome' or 'firefox'.")


def crawl_pagalgana_with_selenium(base_url="https://pagalgana.com/", output_json_file="pagalgana_song_pages.json",
                                  max_crawl_depth=3):
    """
    Crawls Pagalgana.com, handling 'Load More' buttons, to find all nested links
    of pages that contain the audio-container XPath.
    Saves these song page URLs to a JSON file.

    Args:
        base_url (str): The starting URL for the crawl.
        output_json_file (str): The name of the JSON file to save song page URLs.
        max_crawl_depth (int): The maximum depth to crawl (to prevent infinite loops).
    """
    driver = create_webdriver_instance()
    if not driver:
        print("Failed to initialize WebDriver. Exiting.")
        return

    to_visit = deque([(base_url, 0)])  # (URL, current_depth)
    visited_urls = set()
    song_page_urls = []

    AUDIO_CONTAINER_XPATH = '//*[@id="audio-container"]'
    LOAD_MORE_BUTTON_XPATH = '//a[@class="button" and contains(@onclick, "loadMoreCategory")]'

    print(f"Starting crawl from: {base_url} with max depth {max_crawl_depth}")

    while to_visit:
        current_url, current_depth = to_visit.popleft()

        if current_url in visited_urls:
            continue

        if current_depth > max_crawl_depth:
            print(f"Skipping {current_url} - max depth reached ({max_crawl_depth})")
            continue

        print(f"Visiting ({current_depth}): {current_url}")
        visited_urls.add(current_url)

        try:
            driver.get(current_url)
            time.sleep(1)  # Give page some time to load initial content

            # Check if it's a song page
            if driver.find_elements(By.XPATH, AUDIO_CONTAINER_XPATH):
                print(f"  --> Found song page: {current_url}")
                song_page_urls.append(current_url)
                continue  # No need to extract more links from a song page

            # Handle "Load More" button if present
            while True:
                try:
                    # Wait for the button to be clickable
                    load_more_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.XPATH, LOAD_MORE_BUTTON_XPATH))
                    )

                    # Store current page height before clicking
                    last_height = driver.execute_script("return document.body.scrollHeight")

                    print("  Clicking 'Load More' button...")
                    load_more_button.click()

                    # Wait for new content to load (scroll height changes)
                    new_height = last_height
                    scroll_attempts = 0
                    while new_height == last_height and scroll_attempts < 5:  # Max 5 attempts to wait for scroll
                        time.sleep(2)  # Wait for content to load
                        new_height = driver.execute_script("return document.body.scrollHeight")
                        scroll_attempts += 1

                    if new_height == last_height:  # If height didn't change, probably no more content
                        print("  No more content loaded or button disappeared.")
                        break  # Exit the 'Load More' loop

                except (NoSuchElementException, TimeoutException):
                    # Button not found or not clickable, so no more 'Load More'
                    print("  'Load More' button not found or no more content.")
                    break
                except Exception as e:
                    print(f"  Error clicking 'Load More': {e}")
                    break  # Break if any other error occurs

            # After all content is loaded (or no 'Load More' button), parse the HTML
            tree = html.fromstring(driver.page_source)

            # Extract nested links from the fully loaded page
            links = tree.xpath('//a/@href')

            for link in links:
                absolute_url = requests.compat.urljoin(current_url, link)

                # Filter links (same as before)
                if "pagalgana.com" in absolute_url and "#" not in absolute_url and "?" not in absolute_url:
                    if not (absolute_url.endswith(
                            ('.mp3', '.zip', '.rar', '.jpg', '.png', '.gif', '.pdf', '.txt', '.xml', '.css', '.js'))):
                        # Ensure we don't re-add pages that have already been marked as song pages
                        # or pages already in the queue/visited.
                        if absolute_url not in visited_urls and (absolute_url, current_depth + 1) not in to_visit:
                            to_visit.append((absolute_url, current_depth + 1))
                            # print(f"    Added to queue: {absolute_url}") # Uncomment for debugging

        except requests.exceptions.RequestException as e:  # This won't directly happen with Selenium, but keeping for conceptual consistency if mixing
            print(f"  Network error for {current_url}: {e}")
        except Exception as e:
            print(f"  An unexpected error occurred for {current_url}: {e}")

    driver.quit()  # Close the browser when done

    # Save the collected song page URLs to a JSON file
    try:
        with open(output_json_file, 'w', encoding='utf-8') as f:
            json.dump(song_page_urls, f, indent=4)
        print(f"\nCrawl complete. Total {len(song_page_urls)} song pages found and saved to '{output_json_file}'.")
    except IOError as e:
        print(f"Error saving JSON file '{output_json_file}': {e}")


# --- Run the crawler ---
if __name__ == "__main__":
    # You might want to start with a more specific URL to limit the crawl scope,
    # as a full site crawl can take a very long time.
    # For example, to crawl only the A-Z Bollywood section:
    # base_url = "https://pagalgana.com/a-to-z-bollywood/a.html" # Start from 'a' page
    # You'd then need to generate all A-Z base URLs and add them to the initial queue.

    # Example of starting with the main Bollywood category to limit the crawl scope
    crawl_pagalgana_with_selenium(
        base_url="https://pagalgana.com/category/bollywood-mp3-songs.html",
        output_json_file="bollywood_song_pages.json",
        max_crawl_depth=7  # Limit depth to avoid excessive crawling
    )

    # To run a very broad crawl from the main page (be cautious, this can take hours/days):
    # print("\n--- Starting broad crawl from main page (may take a long time!) ---")
    # crawl_pagalgana_with_selenium(
    #     base_url="https://pagalgana.com/",
    #     output_json_file="all_pagalgana_song_pages.json",
    #     max_crawl_depth=5 # Higher depth means much longer crawl
    # )