from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

options = Options()
options.add_argument('--headless=new')
options.add_argument('--window-size=1920,1080')
driver = webdriver.Chrome(options=options)

try:
    driver.get('http://localhost:8088/painel')
    time.sleep(2)
    driver.execute_script("switchModule('projeto');")
    driver.execute_script("loadProjectFromERPDatabase('020-26');")
    time.sleep(1)

    driver.execute_script("""
        const tc = document.querySelectorAll('.table-container')[0];
        tc.style.height = '480px';
        tc.style.maxHeight = '480px';
        tc.style.overflowY = 'auto';
        tc.scrollTop = 1200;
    """)
    time.sleep(1)

    res = driver.execute_script("""
        const tc = document.querySelectorAll('.table-container')[0];
        return {
            clientHeight: tc.clientHeight,
            scrollHeight: tc.scrollHeight,
            scrollTop: tc.scrollTop
        };
    """)
    print('With fixed height and scroll:', res)
finally:
    driver.quit()
