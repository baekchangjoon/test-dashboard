package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiSupport;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.ArrayList;
import java.util.List;
import td.harness.Harness;

public class VetDirectorySteps {

    private Response response;
    private List<Object> vetIds = new ArrayList<>();
    private final List<Integer> statuses = new ArrayList<>();

    @When("the vet client lists all veterinarians")
    public void listsAllVets() {
        response = Harness.authed().get("/api/vets");
    }

    @Then("the vet response body is not empty")
    public void bodyNotEmpty() {
        assertThat(ApiSupport.text(response)).isNotBlank();
    }

    @Given("the vet client has fetched the veterinarian list")
    public void hasFetchedList() {
        response = Harness.authed().get("/api/vets");
        assertThat(response.statusCode()).isEqualTo(200);
        vetIds = new ArrayList<>(ApiSupport.list(response, "id"));
        if (vetIds.isEmpty()) {
            vetIds = new ArrayList<>(ApiSupport.list(response, "vetList.id"));
        }
    }

    @When("the vet client reads each listed veterinarian by id")
    public void readsEachVet() {
        int limit = Math.min(vetIds.size(), 5);
        for (int i = 0; i < limit; i++) {
            Response read = Harness.authed().get("/api/vets/" + vetIds.get(i));
            statuses.add(read.statusCode());
        }
    }

    @Then("every individual veterinarian response has status {int}")
    public void everyVetHasStatus(int status) {
        assertThat(statuses).hasSize(Math.min(vetIds.size(), 5));
        assertThat(statuses).allMatch(s -> s == status);
    }

    @When("the vet client reads veterinarian id {int}")
    public void readsVetById(int id) {
        response = Harness.authed().get("/api/vets/" + id);
    }

    @Then("the vet response status is {int}")
    public void vetStatusIs(int status) {
        assertThat(response.statusCode()).as("body: %s", ApiSupport.text(response)).isEqualTo(status);
    }

    @Then("the vet response is a client error")
    public void vetResponseClientError() {
        assertThat(ApiSupport.isClientError(response.statusCode()))
                .as("status %s, body: %s", response.statusCode(), ApiSupport.text(response)).isTrue();
    }
}
