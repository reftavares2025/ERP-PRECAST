import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

options = Options()
options.add_argument("--headless=new")
options.add_argument("--window-size=1920,1080")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.add_argument("--disable-gpu")

driver = webdriver.Chrome(options=options)
artifact_dir = r"C:\Users\User\.gemini\antigravity-cli\brain\50aab225-be5e-419b-8543-c8060951a884"

try:
    print("Navigating to http://localhost:8088/painel...")
    driver.get("http://localhost:8088/painel")
    time.sleep(3)

    # 1. Capture CAD Integration Screen
    p1 = os.path.join(artifact_dir, "screenshot_fase2_integracao_cad.png")
    driver.save_screenshot(p1)
    print("Saved:", p1)

    # 2. Click on a piece's prancha button to open prancha modal
    buttons = driver.find_elements(By.CLASS_NAME, "btn-prancha")
    if buttons:
        print("Clicking first prancha button...")
        driver.execute_script("arguments[0].click();", buttons[0])
        time.sleep(2)
        p2 = os.path.join(artifact_dir, "screenshot_fase2_prancha_modal.png")
        driver.save_screenshot(p2)
        print("Saved:", p2)

        # Close prancha modal
        driver.execute_script("closePranchaModal();")
        time.sleep(1)

    # 3. Switch to Obras Cadastradas screen
    driver.execute_script("switchSubScreen('obras');")
    time.sleep(2)
    p3 = os.path.join(artifact_dir, "screenshot_fase2_obras_cadastradas.png")
    driver.save_screenshot(p3)
    print("Saved:", p3)

    # 4. Switch to Fabricação screen
    driver.execute_script("switchModule('fabricacao');")
    time.sleep(2)
    p4 = os.path.join(artifact_dir, "screenshot_fase2_fabricacao.png")
    driver.save_screenshot(p4)
    print("Saved:", p4)

finally:
    driver.quit()
    print("Done capturing screenshots.")
