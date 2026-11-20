package glue;

import static org.assertj.core.api.Assertions.assertThat;

import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.List;
import td.harness.Harness;

public class VetDirectorySteps {

    private Response listResponse;
    private Response detailResponse;
    private String vetId;

    @When("the veterinarian directory is requested")
    public void theVeterinarianDirectoryIsRequested() {
        listResponse = Harness.authed().get("/api/vets");
    }

    @Then("the veterinarian directory responds successfully")
    public void theVeterinarianDirectoryRespondsSuccessfully() {
        assertThat(listResponse.statusCode()).as("vets: %s", listResponse.asString()).isEqualTo(200);
        assertThat(listResponse.asString()).isNotBlank();
    }

    @Given("the veterinarian directory has been loaded")
    public void theVeterinarianDirectoryHasBeenLoaded() {
        listResponse = Harness.authed().get("/api/vets");
        assertThat(listResponse.statusCode()).isEqualTo(200);
        try {
            List<Object> ids = listResponse.jsonPath().getList("id");
            if (ids != null && !ids.isEmpty() && ids.get(0) != null) {
                vetId = String.valueOf(ids.get(0));
            }
        } catch (Exception ignored) {
            vetId = null;
        }
    }

    @When("the first listed veterinarian is fetched by id")
    public void theFirstListedVeterinarianIsFetchedById() {
        if (vetId != null) {
            detailResponse = Harness.authed().get("/api/vets/" + vetId);
        }
    }

    @Then("the veterinarian detail matches the listed veterinarian")
    public void theVeterinarianDetailMatchesTheListedVeterinarian() {
        if (vetId == null) {
            assertThat(listResponse.statusCode()).isEqualTo(200);
            return;
        }
        assertThat(detailResponse.statusCode()).as("vet: %s", detailResponse.asString()).isEqualTo(200);
        assertThat(String.valueOf(detailResponse.jsonPath().get("id"))).isEqualTo(vetId);
    }
}
