package td.harness;

import io.pjacoco.testkit.Pjacoco;
import io.restassured.filter.Filter;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * testId별 SUT 요청 수. REST Assured 필터가 응답을 받은 요청마다 하나씩 센다(연결 실패는 SUT에 닿지 않았으므로 세지 않는다).
 * 활성 testId는 pjacoco testkit의 InheritableThreadLocal에서 읽으므로 시나리오가 만든 스레드의 요청도 그 시나리오로 귀속된다.
 * pjacoco는 커버 클래스가 0개인 TC의 .exec를 쓰지 않으므로, 이 수가 0이면 .exec가 없는 것이 정상이다.
 */
public final class RequestCounter {

    private static final Map<String, AtomicInteger> COUNTS = new ConcurrentHashMap<>();
    private static final Filter FILTER = (request, response, context) -> {
        io.restassured.response.Response result = context.next(request, response);
        String testId = Pjacoco.currentTestId();
        if (testId != null) {
            COUNTS.computeIfAbsent(testId, key -> new AtomicInteger()).incrementAndGet();
        }
        return result;
    };

    private RequestCounter() {
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
