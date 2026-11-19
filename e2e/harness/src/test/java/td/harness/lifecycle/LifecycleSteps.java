package td.harness.lifecycle;

import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import td.harness.Harness;

/** CucumberLifecycleTest가 쓰는 표본 step. */
public class LifecycleSteps {

    @When("the sample server is pinged")
    public void ping() {
        Harness.anonymous().get("/api/ping").then().statusCode(204);
    }

    @Then("nothing else happens {int}")
    public void nothing(int number) {
        // 일부러 비어 있다
    }
}
