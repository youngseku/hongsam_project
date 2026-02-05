import time
import os
import io
from playwright.sync_api import sync_playwright
from PIL import Image
import google.generativeai as genai
from dotenv import load_dotenv

# 1. 환경 변수 로드 (API 키)
load_dotenv()
GENAI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GENAI_API_KEY:
    print("❌ 오류: .env 파일에서 GEMINI_API_KEY를 찾을 수 없습니다.")
else:
    genai.configure(api_key=GENAI_API_KEY)

# ==========================================
# 1. 디버깅 크롬 연결 & 이미지 캡처 함수
# ==========================================
def get_images_from_current_chrome(target_url=None):
    print("🕵️ 현재 열려 있는 크롬(디버깅 모드)에 연결을 시도합니다...")
    
    image_data_list = []

    try:
        with sync_playwright() as p:
            # 1. 크롬 연결
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            
            # 2. 탭 확보
            if not context.pages:
                page = context.new_page()
            else:
                page = context.pages[0]

            print("✅ 브라우저 연결 성공!")

            # 3. URL 이동 (입력된 경우만)
            if target_url and len(target_url) > 5:
                print(f"🚀 입력하신 링크로 이동합니다...")
                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                    print("   --> 페이지 이동 완료! (잠시 대기 중)")
                    page.wait_for_timeout(2000)
                except Exception as e:
                    print(f"⚠️ 페이지 이동 중 경고(무시 가능): {e}")
            else:
                print("📍 URL 입력이 없어 현재 보고 있는 페이지를 분석합니다.")

            print(f"📄 현재 페이지 제목: {page.title()}")

            # 4. 스크롤 내리기
            print("📜 페이지 스크롤 시작 (이미지 로딩)...")
            previous_height = 0
            while True:
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(1000)
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == previous_height:
                    break
                previous_height = new_height
            
            print("   --> 스크롤 완료!")

            # 5. 이미지 찾기
            selectors = ["#productDetail img", ".product-detail-content img", ".detail-item img", "img"]
            found_locators = []
            
            for selector in selectors:
                locators = page.locator(selector).all()
                for loc in locators:
                    try:
                        box = loc.bounding_box()
                        if box and box['width'] > 300 and box['height'] > 100: 
                            found_locators.append(loc)
                    except: continue
                if len(found_locators) >= 3: break
            
            unique_locators = found_locators[:10]
            print(f"🎯 발견된 유효 이미지: {len(unique_locators)}장")

            # 6. 화면 캡처
            for i, loc in enumerate(unique_locators):
                try:
                    loc.scroll_into_view_if_needed()
                    page.wait_for_timeout(500)
                    image_bytes = loc.screenshot()
                    pil_image = Image.open(io.BytesIO(image_bytes))
                    image_data_list.append(pil_image)
                    print(f"   [+] 이미지 {i+1} 캡처 성공")
                except Exception as e:
                    print(f"   [-] 이미지 {i+1} 캡처 실패: {e}")
            
            browser.close() 

    except Exception as e:
        print(f"\n🚨 연결 또는 실행 실패: {e}")
        print("💡 [체크리스트]")
        print("1. 크롬이 다 꺼져 있었나요?")
        print("2. 디버깅 명령어로 크롬을 켰나요?")

    return image_data_list

# ==========================================
# 2. Gemini 분석 함수 (이름 통일됨!)
# ==========================================
def analyze_images_with_gemini(images):
    if not images:
        return "수집된 이미지가 없습니다."
    
    print(f"\n🧠 Gemini에게 이미지 {len(images)}장을 보내 분석 중입니다...")
    
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    prompt = """
    당신은 깐깐한 '식품 영양 분석 전문가'입니다. 
    제공된 상품 상세페이지 이미지들을 보고 다음 정보를 찾아 정리해주세요.
    
    **중요: 영양성분표는 보통 이미지의 맨 마지막 부분이나, '상품정보제공고시' 표에 있습니다. 끝까지 꼼꼼히 봐주세요.**
    
    [출력 양식]
    1. 제품명:
    2. 칼로리 (총 내용량 기준):
    3. 주요 영양성분 (100g당 또는 1회 제공량당):
       - 탄수화물:
       - 당류:
       - 단백질:
       - 지방:
       - 나트륨:
    4. 원재료명 (주요 성분 위주로):
    5. 특이사항 (알레르기, 특징 등):
    6. 웰니스 관점 3줄 평가:
    """
    
    request_content = [prompt] + images
    
    try:
        response = model.generate_content(request_content)
        return response.text
    except Exception as e:
        return f"Gemini 분석 중 오류 발생: {e}"

# ==========================================
# 3. 메인 실행 함수
# ==========================================
def main():
    print("\n" + "="*50)
    print("🛒 쿠팡 영양성분 분석기 (최종 수정판)")
    print("="*50)
    
    # 1. URL 입력
    print("분석할 상품 페이지의 URL을 입력하세요.")
    print("(입력 없이 엔터 치면, 현재 크롬 화면을 그대로 분석합니다)")
    input_url = input("🔗 URL 입력: ").strip()

    # 2. 이미지 수집
    images = get_images_from_current_chrome(input_url)
    
    # 3. 분석 (함수 이름 이제 맞음!)
    if images:
        result = analyze_images_with_gemini(images)
        print("\n" + "="*50)
        print("📊 [분석 결과]")
        print("="*50)
        print(result)
    else:
        print("\n❌ 분석할 이미지를 찾지 못했습니다.")

if __name__ == "__main__":
    main()