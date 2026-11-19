package glue;

import io.cucumber.java.en.When;

public class BrokenSteps {

    @When("the broken step runs")
    public void brokenStep() {
        int number = "not an int";
    }
}
