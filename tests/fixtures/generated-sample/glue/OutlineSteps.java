package glue;

import static org.assertj.core.api.Assertions.assertThat;

import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import td.harness.Harness;

public class OutlineSteps {

    private Response page;

    @When("I fetch the page {string}")
    public void fetch(String path) {
        page = Harness.authed().get(path);
    }

    @Then("the page answers {int}")
    public void answers(int expected) {
        assertThat(page.statusCode()).isEqualTo(expected);
    }
}
