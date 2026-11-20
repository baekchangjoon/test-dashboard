package glue;

import static org.assertj.core.api.Assertions.assertThat;

import glue.support.ApiData;
import io.cucumber.java.en.Given;
import io.cucumber.java.en.Then;
import io.cucumber.java.en.When;
import io.restassured.response.Response;
import java.util.List;
import td.harness.Harness;

public class VetDirectorySteps {
    private Response listing;
    private Response response;
    private Integer vetId;

    @When("the vet directory is listed")
    public void listVets() {
        listing = Harness.authed().get("/api/vets");
    }

    @Then("the vet directory listing is successful")
    public void listingOk() {
        assertThat(listing.statusCode()).as(listing.asString()).isEqualTo(200);
        assertThat(listing.asString()).isNotBlank();
    }

    @Given("the vet directory has been listed")
    public void listedBefore() {
        listVets();
    }

    @When("the first listed vet is requested by id")
    public void requestFirst() {
        List<Integer> ids = ApiData.ids(listing);
        if (!ids.isEmpty()) {
            vetId = ids.get(0);
            response = Harness.authed().get("/api/vets/" + vetId);
        }
    }

    @Then("the vet details are returned for that id when the directory is not empty")
    public void vetDetails() {
        assertThat(listing.statusCode()).as(listing.asString()).isEqualTo(200);
        if (vetId != null) {
            assertThat(response.statusCode()).as(response.asString()).isEqualTo(200);
            assertThat(ApiData.extractId(response)).isEqualTo(vetId);
        }
    }
}
