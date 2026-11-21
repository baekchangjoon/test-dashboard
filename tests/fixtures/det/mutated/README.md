# mutated fixture (Task 4, REQ-106 반하드코딩)

petclinic 기준 run(`tests/fixtures/det/petclinic/run`)을 `td.detgen.inputs.project`로 투영한 det 번들 6개 JSON에서
이름·경로·임계값을 체계적으로 바꾼 사본이다. 절대경로는 투영 단계에서 이미 지워져 있다.

`test_req106_mutated_fixture`는 이 번들로 `derive`를 돌린 결과(케이스·생성 불가 전체 직렬화)에
`original-names.txt`의 원본 이름이 하나도 없고, 바뀐 임계값에서 파생한 경계값(예: `stays` 1·2·45·46, `kennelSlot` 199·200·777·778)이 있는지 본다.

## 바꾼 것

- 경로: `/api/` → `/svc/`, `reservations` → `bookings`, `owners`/`pets`/`vets` → `keepers`/`critters`/`medics`
- 패키지·클래스: `petclinic` → `zooapp`, `boarding` → `kennel`, `Reservation*` → `Booking*`(서비스·컨트롤러·예외·DTO 전부), `CustomUserDetailsService.loadUserByUsername` → `…loadUserByHandle`
- 필드: nights→stays, roomNumber→kennelSlot, animalCount→beastTotal, petName→critterTitle, priceTier→rateBand,
  loyaltyPoints→rewardScore, ownerEmail→keeperMail, checkInDate→arrivalDay, depositAmount→prepayment, promoCode→discountKey,
  promoApplied→discountUsed, includeStale→withExpired, recentOnly→latestOnly, minNights→minStays, tier→band, username→handle
- enum: PriceTier{BASIC,PREMIUM,VIP} → RateBand{BRONZE,SILVER,GOLD}, ReservationStatus{CANCELLED,CHECKED_IN,CONFIRMED,PENDING} → BookingState{VOIDED,ARRIVED,LOCKED,WAITING}
- 상수: `ROOM_CAPACITY=2` → `SLOT_LIMIT=3`, `EMAIL` → `CONTACT_EMAIL`(형식 휴리스틱 토큰 `EMAIL`은 유지), `WELCOME10` → `HELLO42`
- 메서드: `getNightlyRate` → `getDailyFee`, `canTransitionTo` → `mayMoveTo`
- 임계값: stays 1..30 → 2..45, kennelSlot 100..499 → 200..777, beastTotal 1..4 → 2..6, critterTitle 길이 2..50 → 3..60,
  rewardScore 500 → 650, 보증금 계수 1.1 → 1.3, 삭제 마감 48시간 → 36시간

plans의 `conditionSha`는 바뀐 조건식으로 다시 계산했다.
