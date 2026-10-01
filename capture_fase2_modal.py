import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

options = Options()
options.add_argument('--headless=new')
options.add_argument('--window-size=1920,1080')
options.add_argument('--no-sandbox')
options.add_argument('--disable-gpu')

driver = webdriver.Chrome(options=options)
artifact_dir = r"C:\Users\User\.gemini\antigravity-cli\brain\50aab225-be5e-419b-8543-c8060951a884"

try:
    url = f"http://localhost:8088/painel?_t={int(time.time())}"
    print("Navigating to:", url)
    driver.get(url)
    time.sleep(3)

    # 1. Populate table with 020-26 pieces
    driver.execute_script("loadProjectFromERPDatabase('020-26');")
    time.sleep(2)
    p1 = os.path.join(artifact_dir, "screenshot_fase2_integracao_cad.png")
    driver.save_screenshot(p1)
    print("Saved:", p1)

    # 2. Open authentic prancha modal for piece PM10
    driver.execute_script("openPranchaModal('PM10', 'PILAR PM10', '40X40', '15.69', '2.51', '6276.0', '/files/pranchas/print_PM10.png', '/files/pranchas/prancha_PM10.pdf');")
    time.sleep(2)
    p2 = os.path.join(artifact_dir, "screenshot_fase2_prancha_modal.png")
    driver.save_screenshot(p2)
    print("Saved:", p2)

finally:
    driver.quit()
    print("Done!")
