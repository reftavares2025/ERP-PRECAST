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

    # 1. Switch to Projeto module
    driver.execute_script("switchModule('projeto');")
    time.sleep(2)

    # 2. Trigger instant load for 020-26
    driver.execute_script("loadProjectFromERPDatabase('020-26');")
    time.sleep(2)
    p_initial = os.path.join(artifact_dir, "screenshot_cad_loaded_initial.png")
    driver.save_screenshot(p_initial)
    print("1. Initial CAD loaded:", p_initial)

    # 3. Test scrolling down in the table
    driver.execute_script("""
        const tc = document.querySelectorAll('.table-container')[0];
        if (tc) {
            tc.scrollTop = 1200;
        }
    """)
    time.sleep(1)
    p_scroll = os.path.join(artifact_dir, "screenshot_table_scrolled_down.png")
    driver.save_screenshot(p_scroll)
    print("2. Scrolled table:", p_scroll)

    # 4. Test collapsing the dropzone to expand table
    driver.execute_script("toggleDropzone();")
    time.sleep(1)
    p_expanded = os.path.join(artifact_dir, "screenshot_table_expanded_fullscreen.png")
    driver.save_screenshot(p_expanded)
    print("3. Expanded table view:", p_expanded)

    # 5. Open VM-03 Modal
    driver.execute_script("""
        openPranchaModal('VM-03', 'VM-03 (20X50X5,18) - 4X', '20x50', '5.18', '0.518', '1295.0', '/files/pranchas/print_VM03.png', '/files/pranchas/prancha_VM03.pdf');
    """)
    time.sleep(2)
    p_vm03 = os.path.join(artifact_dir, "screenshot_vm03_isolated_modal.png")
    driver.save_screenshot(p_vm03)
    print("4. VM-03 modal isolated:", p_vm03)

    # 6. Open PM 27 Modal
    driver.execute_script("""
        openPranchaModal('PM27', 'PILAR PM.27', '40x50', '15.69', '3.14', '7845.0', '/files/pranchas/print_PM27.png', '/files/pranchas/prancha_PM27.pdf');
    """)
    time.sleep(2)
    p_pm27 = os.path.join(artifact_dir, "screenshot_pm27_isolated_modal.png")
    driver.save_screenshot(p_pm27)
    print("5. PM 27 modal isolated:", p_pm27)

finally:
    driver.quit()
    print("All verification screenshots captured successfully!")
