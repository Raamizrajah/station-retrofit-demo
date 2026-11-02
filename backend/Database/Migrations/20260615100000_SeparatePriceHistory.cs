using System;
using Microsoft.EntityFrameworkCore.Migrations;
using Npgsql.EntityFrameworkCore.PostgreSQL.Metadata;

namespace StationRetrofit.Database.Migrations;

/// <inheritdoc />
public partial class SeparatePriceHistory : Migration
{
    /// <inheritdoc />
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        // Step 1: Create the price_history table
        migrationBuilder.CreateTable(
            name: "price_history",
            columns: table => new
            {
                id = table.Column<int>(type: "integer", nullable: false)
                    .Annotation("Npgsql:ValueGenerationStrategy", NpgsqlValueGenerationStrategy.IdentityByDefaultColumn),
                price_entry_id = table.Column<int>(type: "integer", nullable: false),
                product_id = table.Column<int>(type: "integer", nullable: false),
                currency = table.Column<string>(type: "character varying(3)", maxLength: 3, nullable: false),
                amount = table.Column<decimal>(type: "numeric(18,2)", nullable: false),
                price_type = table.Column<int>(type: "integer", nullable: false),
                changed_at = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                change_reason = table.Column<string>(type: "text", nullable: true)
            },
            constraints: table =>
            {
                table.PrimaryKey("PK_price_history", x => x.id);
                table.ForeignKey(
                    name: "FK_price_history_products_product_id",
                    column: x => x.product_id,
                    principalTable: "products",
                    principalColumn: "id",
                    onDelete: ReferentialAction.Cascade);
            });

        migrationBuilder.CreateIndex(
            name: "IX_price_history_product_id",
            table: "price_history",
            column: "product_id");

        migrationBuilder.CreateIndex(
            name: "IX_price_history_price_entry_id",
            table: "price_history",
            column: "price_entry_id");

        // Step 2: Backfill price_history from price_entries (idempotent)
        migrationBuilder.Sql(@"
            INSERT INTO price_history (price_entry_id, product_id, currency, amount, price_type, changed_at)
            SELECT pe.id, pe.product_id, pe.currency, pe.amount, pe.price_type, pe.created_at
            FROM price_entries pe
            WHERE NOT EXISTS (
                SELECT 1 FROM price_history ph
                WHERE ph.price_entry_id = pe.id
            );
        ");

        // Step 3: Drop the audit/description column that moved to history
        migrationBuilder.DropColumn(
            name: "description",
            table: "price_entries");
    }

    /// <inheritdoc />
    protected override void Down(MigrationBuilder migrationBuilder)
    {
        // Restore the dropped column
        migrationBuilder.AddColumn<string>(
            name: "description",
            table: "price_entries",
            type: "text",
            nullable: true);

        // Copy change_reason back to description where possible
        migrationBuilder.Sql(@"
            UPDATE price_entries pe
            SET description = ph.change_reason
            FROM price_history ph
            WHERE ph.price_entry_id = pe.id
              AND ph.change_reason IS NOT NULL;
        ");

        // Drop the price_history table
        migrationBuilder.DropTable(name: "price_history");
    }
}
