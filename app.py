from playwright.sync_api import sync_playwright, TimeoutError
import pandas as pd
import re
import json
from fastapi import FastAPI, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from fastapi.security.api_key import APIKeyHeader
from dotenv import load_dotenv
import os

app = FastAPI()

load_dotenv(dotenv_path=".env.local")

# Read the API key from the environment
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise Exception("API_KEY environment variable not set")

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

class SearchParams(BaseModel):
    business_type: str
    location: str
    total: Optional[int] = 1

def extract_data(selector, page, is_xpath=False):
    try:
        if is_xpath:
            locator = page.locator(f'xpath={selector}')
        else:
            locator = page.locator(selector)
        if locator.count() > 0:
            data = locator.inner_text(timeout=3000)
        else:
            data = ""
            return data
    except TimeoutError:
        return ""

def extract_place_id(href):
    # Extract the place ID from the href using regex
    match = re.search(r'!1s([^!]+)', href)
    if match:
        place_id = match.group(1)
        return place_id
    else:
        return None

def main(business_type, location, total):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        page = browser.new_page(user_agent='Your User Agent String')

        print("Navigating to Google Maps...")
        page.goto("https://www.google.com/maps", timeout=60000)
        page.wait_for_timeout(2000)  # Added initial wait time

        search_query = f"{business_type} in {location}"
        print(f"Searching for '{search_query}'...")
        page.locator('input#searchboxinput').fill(search_query)
        page.keyboard.press("Enter")
        page.wait_for_selector('a[href*="https://www.google.com/maps/place"]')

        page.hover('a[href*="https://www.google.com/maps/place"]')

        no_change_count = 0
        max_no_change = 7
        click_attempts = 0
        max_click_attempts = 3

        # Get the results container
        results_container = page.locator('div[aria-label*="Results for"][role="feed"]')

        place_ids = []
        place_id_set = set()

        print("Collecting place IDs...")
        while True:
            # Scroll within the results container
            results_container.evaluate("node => node.scrollTop = node.scrollHeight")
            page.wait_for_timeout(1000)
            page.wait_for_selector('a[href*="https://www.google.com/maps/place"]')

            # Check if "You've reached the end of the list." is present
            if "You've reached the end of the list." in results_container.inner_text():
                print("Reached the end of the list.")
                break

            # Collect unique place IDs
            listings_elements = page.locator('a[href*="https://www.google.com/maps/place"]')
            current_count = 0
            for elem in listings_elements.all():
                href = elem.get_attribute('href')
                place_id = extract_place_id(href)
                if place_id and place_id not in place_id_set:
                    place_id_set.add(place_id)
                    place_ids.append(place_id)
                    current_count += 1
                else:
                    continue

                if len(place_ids) >= total:
                    break

            if len(place_ids) >= total:
                print(f"Total Found: {len(place_ids)}")
                break
            else:
                if current_count == 0:
                    no_change_count += 1
                    if no_change_count >= max_no_change:
                        if click_attempts >= max_click_attempts:
                            print(f"Arrived at all available\nTotal Found: {len(place_ids)}")
                            break
                        else:
                            click_attempts += 1
                            print(
                                f"Attempting to click on the last listing to load more results (Attempt {click_attempts}/{max_click_attempts})")
                            try:
                                # Click on the last listing
                                last_place_id = place_ids[-1]
                                last_listing = page.locator(f'a[href*="{last_place_id}"]').first
                                last_listing.click()
                                # Wait for the details panel to load
                                page.wait_for_selector('h1.DUwDvf.lfPIob', timeout=60000)
                                page.wait_for_timeout(1000)
                                # Close the details panel
                                page.keyboard.press("Escape")
                                page.wait_for_timeout(1000)
                                no_change_count = 0
                            except Exception as e:
                                print(f"Error during click attempt: {e}")
                                pass
                    else:
                        print(f"No new results found. Attempt {no_change_count}/{max_no_change}")
                else:
                    no_change_count = 0
                    print(f"Currently Found: {len(place_ids)}")

        total_unique = len(place_ids)
        print(f"Total unique places to scrape: {total_unique}")
        print(f"Place IDs collected: {place_ids}")

        # Scraping
        scraped_place_ids = set()
        scraped_count = 0
        previous_place_name = ""
        max_retries = 3  # Maximum number of retries per place

        # Lists to store data
        names_list = []
        website_list = []
        phones_list = []
        address_list = []

        for idx, place_id in enumerate(place_ids):
            print(f"\nProcessing place {idx + 1}/{total_unique} with place_id: {place_id}")
            scraped = False
            for attempt in range(max_retries):
                try:
                    if place_id in scraped_place_ids:
                        print(f"Skipping duplicate place ID: {place_id}")
                        scraped = True
                        break

                    # Locate the listing element by place ID
                    print(f"Locating listing for place_id: {place_id}")
                    listing = page.locator(f'a[href*="{place_id}"]').first
                    if listing.count() == 0:
                        print(f"Listing for place_id {place_id} not found on the page.")
                        raise Exception(f"Listing for place_id {place_id} not found.")

                    listing.scroll_into_view_if_needed()
                    page.wait_for_timeout(500)
                    listing.click()
                    print("Clicked on the listing.")

                    # Wait until the place name changes
                    name_selector = 'h1.DUwDvf.lfPIob'
                    print(f"Waiting for place name to change from '{previous_place_name}'...")
                    page.wait_for_function(
                        f'document.querySelector("{name_selector}") && document.querySelector("{name_selector}").innerText !== "{previous_place_name}"',
                        timeout=5000
                    )

                    # Update previous_place_name
                    current_name = extract_data(name_selector, page)
                    print(f"Extracted place name: {current_name}")
                    if current_name == previous_place_name:
                        print("Place name did not change after clicking. Retrying...")
                        raise Exception("Place name did not change.")
                    previous_place_name = current_name

                    if not current_name:
                        print("Failed to retrieve place name.")
                        raise Exception("Failed to retrieve place name.")

                    scraped_place_ids.add(place_id)
                    scraped_count += 1
                    print(f"Scraped {scraped_count}/{total_unique}: {current_name}")
                    names_list.append(current_name)

                    # Define selectors
                    address_selector = 'button[data-item-id="address"] div.fontBodyMedium'
                    website_selector = 'a[data-item-id="authority"] div.fontBodyMedium'
                    phone_number_selector = 'button[data-item-id^="phone:tel:"] div.fontBodyMedium'

                    # Extract data
                    address = extract_data(address_selector, page)
                    print(f"Address: {address}")
                    address_list.append(address)

                    website = extract_data(website_selector, page)
                    print(f"Website: {website}")
                    website_list.append(website)

                    phone = extract_data(phone_number_selector, page)
                    print(f"Phone: {phone}")
                    phones_list.append(phone)

                    # Close the details panel
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(500)

                    scraped = True
                    break  # Exit the retry loop

                except Exception as e:
                    print(f"Error processing listing (Attempt {attempt + 1}/{max_retries}): {e}")

                    if attempt < max_retries - 1:
                        print("Retrying...")

                        # Click away to another place
                        next_index = idx + 1
                        if next_index < len(place_ids):
                            next_place_id = place_ids[next_index]
                            try:
                                print(f"Clicking away to place_id: {next_place_id}")
                                other_listing = page.locator(f'a[href*="{next_place_id}"]').first
                                other_listing.scroll_into_view_if_needed()
                                page.wait_for_timeout(500)
                                other_listing.click()
                                page.wait_for_timeout(1000)
                                # Close the details panel
                                page.keyboard.press("Escape")
                                page.wait_for_timeout(500)
                            except Exception as e2:
                                print(f"Error clicking away to another place: {e2}")
                        else:
                            # Click on the map area to click away
                            try:
                                print("Clicking on the map to deselect current place...")
                                page.click('canvas', timeout=3000)
                                page.wait_for_timeout(500)
                            except Exception as e2:
                                print(f"Error clicking on map: {e2}")

                        # Now try to click back on the original place
                        page.wait_for_timeout(500)
                    else:
                        # Maximum retries reached
                        print("Maximum retries reached. Moving to next listing.")
                        # Append default values
                        names_list.append("N/A")
                        website_list.append("N/A")
                        phones_list.append("N/A")
                        address_list.append("N/A")
                        # Close the details panel if it's open
                        try:
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(500)
                        except:
                            pass
                        break  # Exit the retry loop

            if not scraped:
                continue  # Move to next place_id

        browser.close()

        # Create a DataFrame
        df = pd.DataFrame({
            'Company Name': names_list,
            'Website': website_list,
            'Phone': phones_list,
            'Address': address_list
        })

        # Filter out entries that do not include the location keyword
        df_filtered = df[df['Address'].str.contains(location, case=False, na=False)]
        df_filtered.reset_index(drop=True, inplace=True)

        # Convert DataFrame to JSON
        result_json = df_filtered.to_json(orient='records')
        print("Final JSON Result:")
        print(result_json)

        # Return the JSON string
        return result_json

# API Key validation dependency
def get_api_key(api_key_header: str = Depends(api_key_header)):
    if api_key_header == API_KEY:
        return api_key_header
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )

@app.post("/search")
def search_business(params: SearchParams, api_key: str = Depends(get_api_key)):
    result_json = main(params.business_type, params.location, params.total)
    return json.loads(result_json)
