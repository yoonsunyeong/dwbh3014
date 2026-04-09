# 사업장 인사/급여 통합 관리 (웹 버전)

Flask + SQLite 기반의 웹 인사관리 프로그램입니다.

## 기능
- 근로자 등록/수정/삭제
- 급여 계산 및 저장
- 임금대장 조회/월별 필터/CSV 내보내기
- 임금명세서 조회
- 연차 사용 등록, 부여일수 수정, 잔여 연차 확인

## 1) 실행 방법
```bash
pip install -r requirements.txt
python app.py
```

브라우저에서 `http://127.0.0.1:5000` 접속

## 2) 주요 파일
- `app.py`: Flask 서버 + DB + 비즈니스 로직
- `templates/dashboard.html`: 웹 화면 템플릿
- `hr_payroll_app.py`: 기존 데스크톱(Tkinter) 버전

## 3) 데이터 파일
- 실행 시 `hr_payroll_web.db` 생성

## 참고
- 공제율(국민연금/건강보험/고용보험/소득세)은 기본 샘플 계산값입니다.
- 실제 운영 전 회사 규정/최신 법령 기준으로 조정하세요.
