#!/usr/bin/env python3
"""Browser regression against the running frontend; fixtures stay inside this test.
Run after `make local` with Playwright installed in a separate testing environment.
"""
import argparse
import json
from playwright.sync_api import sync_playwright, expect


def run(url):
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        for w,h in [(390,844),(768,1024),(1440,900),(844,390)]:
            page=browser.new_page(viewport={'width':w,'height':h})
            page.route('**/api/v1/chat/stream',lambda route:route.fulfill(status=200,content_type='text/event-stream',body='event: done\ndata: '+json.dumps({'answer':('Browser-only scroll fixture.\n\n'*150),'status':'answered','sources':[]})+'\n\n'))
            page.goto(url,wait_until='domcontentloaded')
            expect(page.locator('.suggest-query').first).to_be_visible()
            page.get_by_role('textbox',name='Ask a real estate research question').fill('Browser regression test')
            page.get_by_role('button',name='Submit question').click()
            expect(page.locator('.message.assistant .answer-copy')).to_contain_text('Browser-only scroll fixture')
            scroll=page.locator('.research-scroll')
            page.wait_for_function('''() => {const e=document.querySelector('.research-scroll');return e.scrollHeight-e.scrollTop-e.clientHeight<120}''')
            assert page.evaluate('document.scrollingElement.scrollTop')==0
            scroll.evaluate('e=>e.scrollTop=0')
            expect(page.get_by_role('button',name='Latest message')).to_be_visible()
            page.get_by_role('button',name='Latest message').click()
            page.wait_for_function('''() => {const e=document.querySelector('.research-scroll');return e.scrollHeight-e.scrollTop-e.clientHeight<120}''')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            box=page.locator('.composer').bounding_box()
            assert box and box['y']>=0 and box['y']+box['height']<=h+1
            print(f'PASS chat scroll {w}x{h}')
            page.close()
        browser.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://localhost:3000');run(p.parse_args().url)
