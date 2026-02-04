import base64
import os
import io
from PIL import Image  # 이미지를 다루기 위한 도구
from playwright.sync_api import sync_playwright
import google.generativeai as genai
from dotenv import load_dotenv

# ==========================================
# 1. 설정 (Gemini 설정)
# ==========================================
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("🚨 에러: .env 파일에서 GEMINI_API_KEY를 찾을 수 없습니다.")
    exit()

# 구글 Gemini 설정
genai.configure(api_key=api_key)
# 가장 가볍고 빠른 'Gemini 1.5 Flash' 모델 사용
model = genai.GenerativeModel('gemini-2.5-flash')

# ==========================================
# 2. 크롬(디버깅 모드)에서 이미지 가져오기 (풀 스크롤 버전)
# ==========================================
def get_images_from_current_chrome():
    print("🚀 현재 열려 있는 크롬 브라우저에 접속 시도 중...")
    
    image_data_list = []

    with sync_playwright() as p:
        try:
            # 디버깅 모드로 켜진 크롬(9222 포트)에 연결
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            
            # 쿠팡 탭 찾기
            context = browser.contexts[0]
            target_page = None
            
            for page in context.pages:
                if "쿠팡" in page.title() or "Coupang" in page.title():
                    target_page = page
                    target_page.bring_to_front()
                    print(f"✅ 쿠팡 탭 발견: {page.title()}")
                    break
            
            if not target_page:
                if context.pages:
                    target_page = context.pages[0]
                    print(f"⚠️ 쿠팡 탭을 못 찾아서 현재 보고 있는 탭을 사용합니다.")
                else:
                    return []

            # ---------------------------------------------------------
            # [업그레이드] 페이지 끝까지 스크롤 (Infinite Scroll 처리)
            # ---------------------------------------------------------
            print("📜 페이지 끝까지 스크롤을 시작합니다... (시간이 좀 걸릴 수 있습니다)")
            
            previous_height = 0
            while True:
                # 현재 높이 가져오기
                current_height = target_page.evaluate("document.body.scrollHeight")
                
                # 스크롤을 맨 아래로 내림
                target_page.mouse.wheel(0, 5000) 
                target_page.wait_for_timeout(1000) # 로딩 대기 (1초)
                
                # 더 이상 높이가 안 변하면(바닥에 닿았으면) 중단
                new_height = target_page.evaluate("document.body.scrollHeight")
                if new_height == previous_height:
                    print("   --> 페이지 바닥에 도착했습니다!")
                    break
                
                previous_height = new_height
                print("   ... 읽어들이는 중 ...")

            # ---------------------------------------------------------
            # 이미지 수집 (제한을 좀 더 풂)
            # ---------------------------------------------------------
            # 1. 상세페이지 전체 영역 잡기
            selectors = ["#productDetail img", ".product-detail-content img", ".detail-item img", "img"]
            found_images = []
            
            for selector in selectors:
                elements = target_page.locator(selector).all()
                for img in elements:
                    try:
                        box = img.bounding_box()
                        # 너비 400px 이상, 높이 100px 이상인 '진짜' 정보성 이미지만
                        if box and box['width'] > 400 and box['height'] > 100: 
                            found_images.append(img)
                    except: continue
                
                # 유효한 이미지를 3장 이상 찾았으면 그 선택자가 정답임
                if len(found_images) >= 3: break
            
            # 중복 제거 및 최대 15장까지 수집 (영양정보는 보통 뒤에 있으니 뒤쪽 이미지도 중요)
            # 너무 많으면 Gemini 비용/속도 문제가 있으니 15장 정도로 타협
            unique_images = found_images[:15] 
            print(f"🎯 분석 대상 이미지: {len(unique_images)}개 (상세페이지 전체 스캔 완료)")

            for i, img in enumerate(unique_images):
                src = img.get_attribute("src")
                if src:
                    if src.startswith("//"): src = "https:" + src
                    try:
                        image_bytes = target_page.request.get(src).body()
                        pil_image = Image.open(io.BytesIO(image_bytes))
                        image_data_list.append(pil_image)
                        print(f"   [+] 이미지 {i+1} 수집 완료")
                    except Exception as e:
                        print(f"   [-] 이미지 {i+1} 실패: {e}")
            
            browser.disconnect()

        except Exception as e:
            print(f"🚨 연결 실패: {e}")
            
    return image_data_list

# ==========================================
# 3. Gemini 분석 함수
# ==========================================
def analyze_nutrition_with_gemini(pil_images):
    if not pil_images:
        return "분석할 이미지가 없습니다."

    print("🤖 Gemini 분석 시작...")
    
    # 프롬프트 작성
    prompt = """
    당신은 깐깐한 '식품 영양 분석 전문가'입니다. 
    제공된 이미지들(제품 상세페이지)을 보고 다음 정보를 찾아 정리해주세요.
    
    **중요: 영양성분표는 보통 이미지의 맨 마지막 부분이나, '상품정보제공고시' 표에 있습니다. 끝까지 꼼꼼히 봐주세요.**
    
    [출력 양식]
    1. 제품명:
    2. 칼로리:
    3. 주요 영양성분 (당류, 단백질 등):
    4. 원재료명:
    5. 특이사항 (알레르기 유발 성분 등):
    6. 합성첨가물 유무 및 종류:
    7. 종합 평가:
    

    마지막에 웰니스 관점에서 3줄 요약 평가를 해주세요.
    """
    
    try:
        # 텍스트 프롬프트 + 이미지 리스트를 한 번에 전달
        response = model.generate_content([prompt, *pil_images])
        return response.text
    except Exception as e:
        return f"Gemini 분석 중 에러 발생: {e}"

# ==========================================
# 4. 실행
# ==========================================
if __name__ == "__main__":
    print("⚠️  [주의] 크롬 디버깅 모드가 켜져 있어야 합니다.")
    
    images = get_images_from_current_chrome()
    
    if images:
        result = analyze_nutrition_with_gemini(images)
        print("\n" + "="*50)
        print("💎 Gemini 분석 결과")
        print("="*50)
        print(result)
    else:
        print("이미지를 가져오지 못했습니다.")