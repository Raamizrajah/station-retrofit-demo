using Microsoft.EntityFrameworkCore.Migrations;

namespace StationRetrofit.Database.Migrations;

/// <inheritdoc />
public partial class AddPriceDescription : Migration
{
    /// <inheritdoc />
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.AddColumn<string>(
            name: "description",
            table: "price_entries",
            type: "text",
            nullable: true);
    }

    /// <inheritdoc />
    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.DropColumn(
            name: "description",
            table: "price_entries");
    }
}
