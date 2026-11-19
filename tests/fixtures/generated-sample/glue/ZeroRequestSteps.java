package glue;

import static org.assertj.core.api.Assertions.assertThat;

import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;

public class ZeroRequestSteps {

    private int number;

    @Given("the number {int}")
    public void theNumber(int value) {
        number = value;
    }

    @Then("it is even")
    public void isEven() {
        assertThat(number % 2).isZero();
    }
}
