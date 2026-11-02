using Microsoft.EntityFrameworkCore.Migrations;

namespace StationRetrofit.Database.Migrations;

/// <inheritdoc />
public partial class AddProductCategory : Migration
{
    /// <inheritdoc />
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.AddColumn<string>(
            name: "category",
            table: "products",
            type: "character varying(100)",
            maxLength: 100,
            nullable: true);
    }

    /// <inheritdoc />
    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.DropColumn(
            name: "category",
            table: "products");
    }
}
