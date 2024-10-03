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

# The main function to scrape business data from Google Maps
def main(business_type, location, total):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)" \
             " Chrome/94.0.4606.81 Safari/537.36"
        page = browser.new_page(user_agent=user_agent)

        print("Navigating to Google Maps...")
        page.goto("https://www.google.com/maps", timeout=60000)
        page.wait_for_timeout(2000)  # Added initial wait time

        search_query = f"{business_type} in {location}"
        print(f"Searching for '{search_query}'...")
        page.locator('input#searchboxinput').fill(search_query)
        page.keyboard.press("Enter")
        page.wait_for_selector('a[href*="https://www.google.com/maps/place"]')

        place_ids = []
        place_id_set = set()

        print("Collecting place IDs...")
        while len(place_ids) < total:
            results_container = page.locator('div[aria-label*="Results for"][role="feed"]')
            results_container.evaluate("node => node.scrollTop = node.scrollHeight")
            page.wait_for_timeout(1000)

            listings_elements = page.locator('a[href*="https://www.google.com/maps/place"]')
            for elem in listings_elements.all():
                href = elem.get_attribute('href')
                place_id = extract_place_id(href)
                if place_id and place_id not in place_id_set:
                    place_id_set.add(place_id)
                    place_ids.append(place_id)
                if len(place_ids) >= total:
                    break

        # Scrape data for each place ID
        names_list = []
        website_list = []
        phones_list = []
        address_list = []

        for place_id in place_ids:
            listing = page.locator(f'a[href*="{place_id}"]').first
            listing.click()

            # Scrape data
            current_name = extract_data('h1.DUwDvf.lfPIob', page)
            names_list.append(current_name)
            address = extract_data('button[data-item-id="address"] div.fontBodyMedium', page)
            address_list.append(address)
            website = extract_data('a[data-item-id="authority"] div.fontBodyMedium', page)
            website_list.append(website)
            phone = extract_data('button[data-item-id^="phone:tel:"] div.fontBodyMedium', page)
            phones_list.append(phone)

            page.keyboard.press("Escape")
            page.wait_for_timeout(500)

        browser.close()

        df = pd.DataFrame({
            'Company Name': names_list,
            'Website': website_list,
            'Phone': phones_list,
            'Address': address_list
        })

        df_filtered = df[df['Address'].str.contains(location, case=False, na=False)]
        result_json = df_filtered.to_json(orient='records')
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
