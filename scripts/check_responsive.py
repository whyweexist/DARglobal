#!/usr/bin/env python3
"""Browser layout smoke checks against the running frontend (optional Playwright)."""
import argparse
from playwright.sync_api import sync_playwright

VIEWPORTS = [(320,568),(390,844),(768,1024),(1024,768),(1440,900),(844,390)]


def run(url: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width,height in VIEWPORTS:
            page=browser.new_page(viewport={'width':width,'height':height})
            page.goto(url,wait_until='domcontentloaded')
            page.get_by_role('textbox',name='Ask a real estate research question').wait_for()
            # Wait for client media-query state to settle before checking layout.
            if width <= 900:
                page.locator('#source-navigation').wait_for(state='hidden')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Horizontal overflow at {width}x{height}'
            rect=page.locator('.composer').bounding_box()
            assert rect and rect['y']>=0 and rect['y']+rect['height']<=height+1, f'Composer clipped at {width}x{height}'
            page.locator('.model-trigger').click()
            page.get_by_placeholder('Search free models...').wait_for()
            popover=page.locator('.model-popover').bounding_box()
            assert popover and popover['x']>=0 and popover['x']+popover['width']<=width+1, f'Model menu overflow at {width}x{height}'
            page.keyboard.press('Escape')
            if width<=900:
                page.get_by_role('button',name='Open menu',exact=True).click()
                page.get_by_role('dialog',name='Research sources and history').wait_for()
                page.get_by_role('button',name='Close menu',exact=True).click()
                page.locator('#source-navigation').wait_for(state='hidden')
            if width<=1240:
                page.get_by_role('button',name='Toggle evidence panel',exact=True).click()
                page.get_by_role('dialog',name='Source evidence').wait_for()
                page.get_by_role('button',name='Close evidence panel',exact=True).click()
                page.locator('#evidence-drawer').wait_for(state='hidden')
            print(f'PASS {width}x{height}')
            page.close()
        browser.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://localhost:3000')
    run(parser.parse_args().url)
