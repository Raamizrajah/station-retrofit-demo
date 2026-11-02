using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

namespace StationRetrofit.Database.Migrations;

/// <summary>
/// BAD: Drops columns before backfilling data to the new table.
/// </summary>
public partial class MovePriceMetadata : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        // Creates the new table
        migrationBuilder.CreateTable(
            name: "price_metadata",
            columns: table => new
            {
                id = table.Column<int>(type: "integer", nullable: false)
                    .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                price_entry_id = table.Column<int>(type: "integer", nullable: false),
                description = table.Column<string>(type: "text", nullable: true),
                price_type = table.Column<int>(type: "integer", nullable: false, defaultValue: 0)
            },
            constraints: table =>
            {
                table.PrimaryKey("PK_price_metadata", x => x.id);
            });

        // BUG: Drops columns BEFORE backfilling data!
        // The data in these columns will be permanently lost.
        migrationBuilder.DropColumn(name: "description", table: "price_entries");
        migrationBuilder.DropColumn(name: "price_type", table: "price_entries");
    }

    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.AddColumn<string>(
            name: "description", table: "price_entries",
            type: "text", nullable: true);
        migrationBuilder.AddColumn<int>(
            name: "price_type", table: "price_entries",
            type: "integer", nullable: false, defaultValue: 0);
        migrationBuilder.DropTable(name: "price_metadata");
    }
}
