package td.harness;

import io.pjacoco.testkit.restassured.PjacocoRestAssured;
import io.restassured.RestAssured;
import io.restassured.specification.RequestSpecification;

/**
 * 생성된 step 정의가 쓰는 유일한 진입점(계약은 CONTRACT.md).
 *
 * <p>요청에 붙는 커버리지 귀속 헤더와 요청 계수는 REST Assured 전역 필터로 한 번 설치한다.
 * 그래서 step 코드가 {@code RestAssured.given()}을 직접 써도 같은 시나리오로 귀속된다.
 */
public final class Harness {

    private static boolean installed;

    private Harness() {
    }

    /** 대상 서버의 base URL(경로 없음). 속성은 호출 때마다 읽는다. */
    public static String baseUrl() {
        String value = System.getProperty("td.base-url");
        if (value == null || value.isBlank()) {
            throw new IllegalStateException("시스템 속성 td.base-url이 필요하다");
        }
        return value.endsWith("/") ? value.substring(0, value.length() - 1) : value;
    }

    /** 로그인해서 얻은 토큰을 Bearer 헤더로 붙인 요청 명세. 로그인은 스위트당 한 번이다. */
    public static RequestSpecification authed() {
        return anonymous().header("Authorization", "Bearer " + AuthSession.token());
    }

    /** 인증 헤더가 없는 요청 명세. */
    public static RequestSpecification anonymous() {
        install();
        return RestAssured.given().baseUri(baseUrl());
    }

    /** 전역 필터를 한 번만 설치한다(baggage -> 요청 수 순서). */
    static synchronized void install() {
        if (!installed) {
            RestAssured.filters(PjacocoRestAssured.baggageFilter(), RequestCounter.filter());
            installed = true;
        }
    }
}
