Feature: Page fetch

  Scenario Outline: fetch <path>
    When I fetch the page "<path>"
    Then the page answers 200

    Examples:
      | path        |
      | /api/vets   |
      | /api/owners |
