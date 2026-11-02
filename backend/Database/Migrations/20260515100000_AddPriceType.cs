using Microsoft.EntityFrameworkCore.Migrations;

namespace StationRetrofit.Database.Migrations;

/// <inheritdoc />
public partial class AddPriceType : Migration
{
    /// <inheritdoc />
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.AddColumn<int>(
            name: "price_type",
            table: "price_entries",
            type: "integer",
            nullable: false,
            defaultValue: 0);
    }

    /// <inheritdoc />
    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.DropColumn(
            name: "price_type",
            table: "price_entries");
    }
}
