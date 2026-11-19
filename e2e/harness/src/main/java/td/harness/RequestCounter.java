package td.harness;

import io.pjacoco.testkit.Pjacoco;
import io.restassured.filter.Filter;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * testId별 SUT 요청 수. REST Assured 필터가 요청을 보낸 것마다 하나씩 센다(연결 실패는 SUT에 닿지 않았으므로 세지 않는다).
 * 활성 testId는 pjacoco testkit의 InheritableThreadLocal에서 읽으므로 시나리오가 만든 스레드의 요청도 그 시나리오로 귀속된다.
 * pjacoco는 커버 클래스가 0개인 TC의 .exec를 쓰지 않으므로, 이 수가 0이면 .exec가 없는 것이 정상이다.
 */
public final class RequestCounter {

    private static final Map<String, AtomicInteger> COUNTS = new ConcurrentHashMap<>();
    /**
     * 요청을 보낸 뒤 응답을 읽다가 실패(읽기 타임아웃 등)해도 SUT가 요청을 처리했을 수 있으므로 센다(finally).
     * 연결 자체가 안 된 경우(연결 거부, 이름 해석 실패, 연결 타임아웃)만 SUT에 닿지 않았으므로 세지 않는다.
     */
    private static final Filter FILTER = (request, response, context) -> {
        boolean reachedServer = true;
        try {
            return context.next(request, response);
        } catch (Throwable failure) { // REST Assured/Apache가 검사 예외를 몰래 던질 수 있다
            reachedServer = !neverConnected(failure);
            throw failure;
        } finally {
            String testId = Pjacoco.currentTestId();
            if (reachedServer && testId != null) {
                COUNTS.computeIfAbsent(testId, key -> new AtomicInteger()).incrementAndGet();
            }
        }
    };

    private RequestCounter() {
    }

    static boolean neverConnected(Throwable failure) {
        for (Throwable cause = failure; cause != null; cause = cause.getCause() == cause ? null : cause.getCause()) {
            if (cause instanceof java.net.ConnectException || cause instanceof java.net.UnknownHostException
                    || cause instanceof java.net.NoRouteToHostException
                    || cause.getClass().getSimpleName().contains("ConnectTimeout")) {
                return true;
            }
        }
        return false;
    }

    public static Filter filter() {
        return FILTER;
    }

    public static int count(String testId) {
        AtomicInteger counter = COUNTS.get(testId);
        return counter == null ? 0 : counter.get();
    }

    /** 센 수를 돌려주고 지운다. */
    public static int take(String testId) {
        AtomicInteger counter = COUNTS.remove(testId);
        return counter == null ? 0 : counter.get();
    }

    public static void reset(String testId) {
        COUNTS.remove(testId);
    }
}
