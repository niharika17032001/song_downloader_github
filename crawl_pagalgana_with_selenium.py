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
        options.add_argument("--headless")  # Run in headless mode (no GUI)
        options.add_argument("--no-sandbox")  # Required for GitHub Actions' ubuntu-latest
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--window-size=1920,1080")  # Set a window size for headless
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

        # Point to the ChromeDriver executable available in GitHub Actions runner
        # This path is common for apt-get installed chromedriver on Ubuntu
        service = webdriver.ChromeService(executable_path="/usr/bin/chromedriver")

        try:
            driver = webdriver.Chrome(service=service, options=options)
            return driver
        except WebDriverException as e:
            print(f"Error initializing ChromeDriver. Error: {e}")
            return None
    # Add Firefox support if needed, ensure geckodriver is also installed in GH Actions
    else:
        raise ValueError("Unsupported browser type. Only 'chrome' is configured for GitHub Actions.")


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
                        if absolute_url not in visited_urls and (absolute_url, current_depth + 1) not in to_visit:
                            to_visit.append((absolute_url, current_depth + 1))

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
    crawl_pagalgana_with_selenium(
        base_url="https://pagalgana.com/category/bollywood-mp3-songs.html",
        output_json_file="bollywood_song_pages.json",
        max_crawl_depth=3
    )