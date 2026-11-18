package td.minisut.api;

import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

import io.restassured.RestAssured;
import io.restassured.filter.Filter;
import io.restassured.filter.FilterContext;
import io.restassured.response.Response;
import io.restassured.specification.FilterableRequestSpecification;
import io.restassured.specification.FilterableResponseSpecification;
import org.junit.jupiter.api.extension.AfterEachCallback;
import org.junit.jupiter.api.extension.BeforeEachCallback;
import org.junit.jupiter.api.extension.ExtensionContext;

/**
 * Routes per-test-case code coverage for the out-of-process black-box suite, using the
 * <a href=
 * "https://github.com/baekchangjoon/parallel-per-test-coverage">parallel-per-test-coverage</a>
 * java agent attached to the server under test.
 *
 * <p>
 * It is <strong>opt-in</strong>: enable by pointing it at the agent's control endpoint
 * with {@code -Dpjacoco.control-url=http://127.0.0.1:6310}. With no such property it does
 * nothing, so the normal black-box run is unaffected. When enabled it:
 * <ul>
 * <li>opens a coverage boundary before each test
 * ({@code POST /__coverage__/test/start?testId=...}),</li>
 * <li>tags <em>every</em> REST Assured request with an OpenTelemetry baggage header
 * {@code baggage: test.id=<ClassName#method>} so the agent attributes the server-side
 * coverage to the right test case, and</li>
 * <li>closes the boundary after each test
 * ({@code POST /__coverage__/test/stop?testId=...&result=...}), which flushes one
 * vanilla-JaCoCo {@code <testId>.exec} per test case.</li>
 * </ul>
 *
 * <p>
 * Every control-plane call is best-effort: any failure is swallowed so coverage routing
 * can never fail a black-box assertion. The active test id is held in an
 * {@link InheritableThreadLocal} so the worker threads that {@code ConcurrencyBlackBoxIT}
 * spawns inherit it, and their requests stay attributed to the test that launched them.
 */
public class PerTestCoverageExtension implements BeforeEachCallback, AfterEachCallback {

	/** The test id active on the current thread; inherited by threads a test spawns. */
	static final InheritableThreadLocal<String> CURRENT_TEST_ID = new InheritableThreadLocal<>();

	/**
	 * Agent control endpoint, e.g. {@code http://127.0.0.1:6310}; null disables routing.
	 */
	private static final String CONTROL_URL = System.getProperty("pjacoco.control-url");

	private static final HttpClient HTTP = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();

	static {
		// Stamp the baggage header onto every REST Assured request, on whichever thread
		// issues it.
		RestAssured.filters(new BaggageFilter());
	}

	@Override
	public void beforeEach(ExtensionContext context) {
		String testId = testId(context);
		CURRENT_TEST_ID.set(testId);
		control("start", "testId=" + enc(testId));
	}

	@Override
	public void afterEach(ExtensionContext context) {
		String result = context.getExecutionException().isPresent() ? "failed" : "passed";
		control("stop", "testId=" + enc(testId(context)) + "&result=" + result);
		CURRENT_TEST_ID.remove();
	}

	private static String testId(ExtensionContext context) {
		return context.getRequiredTestClass().getSimpleName() + "#" + context.getRequiredTestMethod().getName();
	}

	private static String enc(String value) {
		return URLEncoder.encode(value, StandardCharsets.UTF_8);
	}

	/** Fire a control-plane request; never throws (coverage must not break the suite). */
	private static void control(String op, String query) {
		if (CONTROL_URL == null || CONTROL_URL.isBlank()) {
			return;
		}
		try {
			HttpRequest request = HttpRequest.newBuilder()
				.uri(URI.create(CONTROL_URL + "/__coverage__/test/" + op + "?" + query))
				.timeout(Duration.ofSeconds(3))
				.POST(HttpRequest.BodyPublishers.noBody())
				.build();
			HTTP.send(request, HttpResponse.BodyHandlers.discarding());
		}
		catch (InterruptedException ex) {
			Thread.currentThread().interrupt();
		}
		catch (Exception ex) {
			System.err.println("[pjacoco] control " + op + " failed: " + ex);
		}
	}

	/** Adds {@code baggage: test.id=<id>} to each request while a test id is active. */
	static final class BaggageFilter implements Filter {

		@Override
		public Response filter(FilterableRequestSpecification requestSpec, FilterableResponseSpecification responseSpec,
				FilterContext ctx) {
			String id = CURRENT_TEST_ID.get();
			if (id != null) {
				requestSpec.header("baggage", "test.id=" + id);
			}
			return ctx.next(requestSpec, responseSpec);
		}

	}

}
