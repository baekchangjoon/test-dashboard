package td.runner;

import org.junit.platform.suite.api.IncludeEngines;
import org.junit.platform.suite.api.SelectClasspathResource;
import org.junit.platform.suite.api.Suite;

/**
 * generation의 features를 Cucumber 엔진으로 실행하는 진입점이다.
 * glue 패키지, 플러그인, dry-run 여부 등은 build.gradle이 만든 junit-platform.properties(cucumber.*)가 정한다.
 */
@Suite
@IncludeEngines("cucumber")
@SelectClasspathResource("features")
public class RunCucumberTest {
}
